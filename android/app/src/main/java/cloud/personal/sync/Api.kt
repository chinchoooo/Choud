package cloud.personal.sync

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okio.BufferedSink
import org.json.JSONObject
import java.io.IOException
import java.io.InputStream
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

/** The server could not be reached (offline, timeout, DNS): retry later. */
class ApiUnavailable(message: String) : IOException(message)

open class ApiError(val status: Int, val detail: String) : IOException("$status: $detail") {
    val transient: Boolean get() = status >= 500 || status == 429
}

/** The login is no longer valid; the user has to sign in again. */
class AuthError(detail: String) : ApiError(401, detail)

/** A conditional write was refused: the file already exists / changed. */
class VersionConflict(detail: String) : ApiError(409, detail)

interface TokenStore {
    var access: String
    var refresh: String
}

data class RemoteFile(val id: String, val path: String, val contentHash: String)
data class UploadResult(val fileId: String, val contentHash: String)

data class FolderItem(val id: String, val name: String)

data class RemoteItem(
    val id: String,
    val name: String,
    val size: Long,
    val mime: String,
    val favorite: Boolean,
    val folderPath: String,
    val takenAtMillis: Long?,
    val createdAtMillis: Long?,
    /** The phone's own last-modified time for the file, if the server has it. */
    val modifiedAtMillis: Long? = null,
) {
    /** For the photo timeline: when it was taken, else the file's own date, else the upload time. */
    val sortMillis: Long get() = takenAtMillis ?: modifiedAtMillis ?: createdAtMillis ?: 0L

    /** The date shown next to a file: its own modified date, else when it was uploaded. */
    val displayMillis: Long get() = modifiedAtMillis ?: createdAtMillis ?: 0L
}

data class Listing(val folders: List<FolderItem>, val files: List<RemoteItem>)
data class PhotoPage(val items: List<RemoteItem>, val total: Int)
data class Usage(val usedBytes: Long, val quotaBytes: Long, val fileCount: Int)

private fun parseMillis(raw: String?): Long? =
    if (raw.isNullOrEmpty() || raw == "null") null
    else try {
        java.time.OffsetDateTime.parse(raw).toInstant().toEpochMilli()
    } catch (_: Exception) {
        null
    }

private fun JSONObject.toItem() = RemoteItem(
    id = getString("id"),
    name = getString("name"),
    size = optLong("size", 0),
    mime = optString("mime_type", "").let { if (it == "null") "" else it },
    favorite = optBoolean("is_favorite", false),
    folderPath = optString("folder_path", "").let { if (it == "null") "" else it },
    takenAtMillis = parseMillis(if (isNull("taken_at")) null else optString("taken_at")),
    createdAtMillis = parseMillis(optString("created_at")),
    modifiedAtMillis = parseMillis(if (isNull("modified_at")) null else optString("modified_at")),
)

/** A request body that re-opens its source each time, so a retry after a token refresh works. */
private class StreamBody(
    private val open: () -> InputStream,
    private val offset: Long,
    private val length: Long,
    private val type: String,
    private val onBytes: (Long) -> Unit = {},
) : RequestBody() {
    override fun contentType() = type.toMediaType()
    override fun contentLength() = length
    override fun writeTo(sink: BufferedSink) {
        open().use { stream ->
            var toSkip = offset
            while (toSkip > 0) {
                val skipped = stream.skip(toSkip)
                if (skipped <= 0) throw IOException("could not seek to $offset")
                toSkip -= skipped
            }
            var remaining = length
            val buffer = ByteArray(64 * 1024)
            while (remaining > 0) {
                val read = stream.read(buffer, 0, minOf(buffer.size.toLong(), remaining).toInt())
                if (read < 0) throw IOException("file shrank while uploading")
                sink.write(buffer, 0, read)
                remaining -= read
                onBytes(length - remaining)
            }
        }
    }
}

fun sha256Hex(open: () -> InputStream, onBytes: (Long) -> Unit = {}): String {
    val digest = MessageDigest.getInstance("SHA-256")
    open().use { stream ->
        val buffer = ByteArray(64 * 1024)
        var total = 0L
        while (true) {
            val read = stream.read(buffer)
            if (read < 0) break
            digest.update(buffer, 0, read)
            total += read
            onBytes(total)
        }
    }
    return digest.digest().joinToString("") { "%02x".format(it) }
}

/** HTTP client for the Personal Cloud API; port of client/cloudsync/api.py (the reference). */
class ApiClient(
    baseUrl: String,
    private val tokens: TokenStore,
    private val http: OkHttpClient = Net.bulk(),
    private val log: (String) -> Unit = {},
) {
    private val base = baseUrl.trim().trimEnd('/')
    private var snapshotEtag: String? = null
    private var snapshotCache: Map<String, RemoteFile>? = null

    private fun detailText(raw: String, fallback: String): String =
        try {
            val detail = JSONObject(raw).opt("detail")
            if (detail is JSONObject) detail.optString("message", detail.toString())
            else detail?.toString() ?: raw
        } catch (_: Exception) {
            raw.ifEmpty { fallback }
        }

    private fun ms(startedNanos: Long) = (System.nanoTime() - startedNanos) / 1_000_000

    private fun raiseForError(response: Response, path: String = "") {
        if (response.code < 400) return
        val raw = response.body?.string().orEmpty()
        val text = detailText(raw, response.message)
        log("   server said (${response.code} $path): ${text.take(300)}")
        if (response.code == 409) {
            val code = try {
                JSONObject(raw).optJSONObject("detail")?.optString("code")
            } catch (_: Exception) {
                null
            }
            if (code == "version_conflict") throw VersionConflict(text)
        }
        if (response.code == 401) throw AuthError(text)
        throw ApiError(response.code, text)
    }

    /** One request; `build` is called per attempt so bodies are fresh after a refresh. */
    private fun send(
        path: String,
        retryAuth: Boolean = true,
        build: (Request.Builder) -> Request.Builder = { it },
    ): Response {
        val usedAccess = tokens.access
        val builder = Request.Builder().url(base + path)
        if (usedAccess.isNotEmpty()) builder.header("Authorization", "Bearer $usedAccess")
        val request = build(builder).build()
        val started = System.nanoTime()
        log("-> ${request.method} $path")
        val response = try {
            http.newCall(request).execute()
        } catch (e: IOException) {
            log("!! ${request.method} $path network error after ${ms(started)} ms: ${e.javaClass.simpleName}: ${e.message}")
            throw ApiUnavailable(e.message ?: e.javaClass.simpleName)
        }
        log("<- ${response.code} ${request.method} $path (${ms(started)} ms)")
        if (response.code == 401 && retryAuth && tokens.refresh.isNotEmpty() && !path.startsWith("/api/auth/")) {
            response.close()
            log("   access token expired, refreshing")
            refreshIfStale(usedAccess)
            return send(path, false, build)
        }
        try {
            raiseForError(response, path)
        } finally {
            if (response.code >= 400) response.close()
        }
        return response
    }

    private fun json(obj: JSONObject): RequestBody =
        obj.toString().toRequestBody("application/json".toMediaType())

    private fun Response.jsonBody(): JSONObject = use { JSONObject(it.body!!.string()) }

    /** Unauthenticated reachability check; returns the health JSON. */
    fun health(): String =
        send("/api/health", false).use { it.body!!.string() }

    fun login(email: String, password: String, otp: String = "") {
        val body = send("/api/auth/login", false) {
            val payload = JSONObject().put("email", email).put("password", password)
            if (otp.isNotEmpty()) payload.put("otp", otp)
            it.post(json(payload))
        }.jsonBody()
        tokens.access = body.getString("access_token")
        tokens.refresh = body.getString("refresh_token")
        log("   logged in")
    }

    /**
     * Several uploads can hit a 401 at once, and refresh tokens are single-use: only the
     * first caller refreshes; the others see the new token and just retry.
     */
    @Synchronized
    fun refreshIfStale(usedAccess: String) {
        if (tokens.access != usedAccess && tokens.access.isNotEmpty()) return
        refresh()
    }

    fun refresh() {
        if (tokens.refresh.isEmpty()) throw AuthError("not logged in")
        val body = try {
            send("/api/auth/refresh", false) {
                it.post(json(JSONObject().put("refresh_token", tokens.refresh)))
            }.jsonBody()
        } catch (e: AuthError) {
            throw AuthError("your session expired - log in again")
        }
        tokens.access = body.getString("access_token")
        tokens.refresh = body.getString("refresh_token")
        log("   token refreshed")
    }

    /** Remote files by path. An unchanged tree is a bodyless 304 (cheap on mobile data). */
    @Synchronized
    fun snapshot(): Map<String, RemoteFile> {
        val etag = snapshotEtag
        val cached = snapshotCache
        val response = send("/api/sync/snapshot") { b ->
            if (etag != null && cached != null) b.header("If-None-Match", etag) else b
        }
        response.use {
            if (it.code == 304 && cached != null) return cached
            val files = JSONObject(it.body!!.string()).getJSONArray("files")
            val map = HashMap<String, RemoteFile>()
            for (i in 0 until files.length()) {
                val f = files.getJSONObject(i)
                map[f.getString("path")] = RemoteFile(
                    f.getString("id"), f.getString("path"), f.optString("content_hash", "")
                )
            }
            snapshotCache = map
            snapshotEtag = it.header("ETag")
            return map
        }
    }

    /** Id of the server folder at `path` (created if missing). Idempotent. */
    fun ensureFolder(path: String): String =
        send("/api/sync/folders") { it.post(json(JSONObject().put("path", path))) }
            .jsonBody().getString("id")

    /**
     * Create-only upload: `base_version_id=none`, so a name clash is a [VersionConflict]
     * rather than a silent new version of someone else's photo.
     */
    fun uploadNew(
        open: () -> InputStream,
        name: String,
        folderId: String,
        size: Long,
        mime: String,
        contentHash: String,
        resumeId: String? = null,
        onSession: (String?) -> Unit = {},
        onBytes: (Long) -> Unit = {},
        takenAt: String? = null,
        modifiedAt: String? = null,
    ): UploadResult =
        if (size <= CHUNKED_THRESHOLD) uploadSmall(open, name, folderId, size, mime, onBytes, takenAt, modifiedAt)
        else uploadChunked(open, name, folderId, size, contentHash, resumeId, onSession, onBytes, takenAt, modifiedAt)

    private fun result(body: JSONObject) =
        UploadResult(body.getString("id"), body.optString("content_hash", ""))

    private fun uploadSmall(
        open: () -> InputStream, name: String, folderId: String, size: Long, mime: String,
        onBytes: (Long) -> Unit,
        takenAt: String?,
        modifiedAt: String?,
    ): UploadResult =
        result(
            send("/api/files/upload") {
                val form = MultipartBody.Builder().setType(MultipartBody.FORM)
                    .addFormDataPart("name", name)
                    .addFormDataPart("folder_id", folderId)
                    .addFormDataPart("base_version_id", "none")
                    .apply { if (takenAt != null) addFormDataPart("taken_at", takenAt) }
                    .apply { if (modifiedAt != null) addFormDataPart("modified_at", modifiedAt) }
                    .addFormDataPart("file", name, StreamBody(open, 0, size, mime, onBytes))
                    .build()
                it.post(form)
            }.jsonBody()
        )

    private fun uploadChunked(
        open: () -> InputStream,
        name: String,
        folderId: String,
        size: Long,
        contentHash: String,
        resumeId: String?,
        onSession: (String?) -> Unit,
        onBytes: (Long) -> Unit,
        takenAt: String?,
        modifiedAt: String?,
    ): UploadResult {
        var session: JSONObject? = null
        if (resumeId != null) {
            try {
                val s = send("/api/uploads/$resumeId").jsonBody()
                if (s.getString("status") == "pending") session = s
            } catch (e: ApiError) {
                if (e.status != 404 && e.status != 409) throw e // expired or swept: start over
            }
        }
        if (session == null) {
            val payload = JSONObject()
                .put("file_name", name).put("file_size", size).put("chunk_size", CHUNK_SIZE)
                .put("expected_hash", contentHash).put("folder_id", folderId)
                .put("base_version_id", "none")
            if (takenAt != null) payload.put("taken_at", takenAt)
            if (modifiedAt != null) payload.put("modified_at", modifiedAt)
            val created = send("/api/uploads") { it.post(json(payload)) }.jsonBody()
            session = send("/api/uploads/${created.getString("id")}").jsonBody()
            onSession(session.getString("id"))
        }
        val uploadId = session.getString("id")
        log("   chunked upload $uploadId: ${session.getJSONArray("missing_chunk_indices").length()} chunk(s) to send")
        val chunkBytes = session.getLong("chunk_size")
        val missing = session.getJSONArray("missing_chunk_indices")
        for (i in 0 until missing.length()) {
            val index = missing.getInt(i)
            val offset = index * chunkBytes
            val length = minOf(chunkBytes, size - offset)
            log("   chunk ${i + 1}/${missing.length()} (index $index, $length bytes) of upload $uploadId")
            send("/api/uploads/$uploadId/chunks/$index") {
                val form = MultipartBody.Builder().setType(MultipartBody.FORM)
                    .addFormDataPart(
                        "chunk", "chunk",
                        StreamBody(open, offset, length, "application/octet-stream") { sent ->
                            onBytes(offset + sent)
                        },
                    )
                    .build()
                it.post(form)
            }.close()
        }
        return try {
            val done = result(
                send("/api/uploads/$uploadId/complete") { it.post(ByteArray(0).toRequestBody(null)) }
                    .jsonBody()
            )
            onSession(null)
            done
        } catch (e: VersionConflict) {
            onSession(null) // the server consumed the session; nothing left to resume
            throw e
        }
    }

    // ---------------------------------------------------------------- browsing

    private fun parseListing(body: JSONObject): Listing {
        val folders = body.getJSONArray("subfolders")
        val files = body.getJSONArray("files")
        return Listing(
            (0 until folders.length()).map { folders.getJSONObject(it).let { f -> FolderItem(f.getString("id"), f.getString("name")) } },
            (0 until files.length()).map { files.getJSONObject(it).toItem() },
        )
    }

    private fun directoryPath(folderId: String?) = "/api/files" + if (folderId == null) "" else "?folder_id=$folderId"

    /** The last listing of this folder the server sent, if any (instant, no network). */
    fun cachedDirectory(folderId: String?): Listing? =
        ListCache.get(directoryPath(folderId))?.let { runCatching { parseListing(JSONObject(it)) }.getOrNull() }

    fun listDirectory(folderId: String?): Listing {
        val path = directoryPath(folderId)
        val body = send(path).jsonBody()
        ListCache.put(path, body.toString())
        return parseListing(body)
    }

    private fun parsePage(body: JSONObject): PhotoPage {
        val items = body.getJSONArray("items")
        return PhotoPage((0 until items.length()).map { items.getJSONObject(it).toItem() }, body.getInt("total"))
    }

    private fun photosPath(kind: String, offset: Int, limit: Int) = "/api/library/photos?kind=$kind&offset=$offset&limit=$limit"

    /** The last page of photos the server sent for these arguments, if any (instant, no network). */
    fun cachedPhotos(kind: String, offset: Int, limit: Int): PhotoPage? =
        ListCache.get(photosPath(kind, offset, limit))?.let { runCatching { parsePage(JSONObject(it)) }.getOrNull() }

    fun listPhotos(kind: String, offset: Int, limit: Int): PhotoPage {
        val path = photosPath(kind, offset, limit)
        val body = send(path).jsonBody()
        if (offset == 0) ListCache.put(path, body.toString())
        return parsePage(body)
    }

    fun usage(): Usage {
        val body = send("/api/library/usage").jsonBody()
        return Usage(body.getLong("used_bytes"), body.getLong("quota_bytes"), body.getInt("file_count"))
    }

    /**
     * Sets the phone's own dates on a file that is already on the server. Returns false when the
     * server did not echo `modified_at` back: an older server silently ignores fields it does not
     * know, and a date fix that did nothing must not be recorded as done.
     */
    fun patchDates(fileId: String, takenAt: String?, modifiedAt: String?): Boolean {
        val body = JSONObject()
        if (modifiedAt != null) body.put("modified_at", modifiedAt)
        if (takenAt != null) body.put("taken_at", takenAt)
        val reply = send("/api/files/$fileId") { it.patch(json(body)) }.jsonBody()
        return reply.has("modified_at")
    }

    /** Gives photos uploaded without a date their real one (from the name or EXIF). Returns "fixed|checked". */
    fun fixDates(apply: Boolean): Pair<Int, Int> {
        val body = JSONObject().put("dry_run", !apply)
        val reply = send("/api/library/fix-dates") { it.post(json(body)) }.jsonBody()
        return reply.getInt("fixed") to reply.getInt("checked")
    }

    fun moveFile(id: String, folderId: String?) {
        val body = JSONObject().put("folder_id", folderId ?: JSONObject.NULL)
        send("/api/files/$id") { it.patch(json(body)) }.close()
    }

    fun moveFolder(id: String, parentId: String?) {
        val body = JSONObject().put("parent_id", parentId ?: JSONObject.NULL)
        send("/api/folders/$id") { it.patch(json(body)) }.close()
    }

    fun deleteFile(id: String) {
        send("/api/files/$id") { it.delete() }.close()
    }

    fun deleteFolder(id: String) {
        send("/api/folders/$id") { it.delete() }.close()
    }

    fun restoreFile(id: String) {
        send("/api/trash/$id/restore") { it.post(ByteArray(0).toRequestBody(null)) }.close()
    }

    /** Several files and folders as one .zip, streamed to `dest`. Returns the size. */
    fun downloadZip(fileIds: List<String>, folderIds: List<String>, dest: java.io.File): Long {
        val body = JSONObject()
            .put("file_ids", org.json.JSONArray(fileIds))
            .put("folder_ids", org.json.JSONArray(folderIds))
        val response = send("/api/archive/zip") { it.post(json(body)) }
        response.use {
            dest.parentFile?.mkdirs()
            var done = 0L
            it.body!!.byteStream().use { input ->
                dest.outputStream().use { out ->
                    val buffer = ByteArray(64 * 1024)
                    while (true) {
                        val read = input.read(buffer)
                        if (read < 0) break
                        out.write(buffer, 0, read)
                        done += read
                    }
                }
            }
            return done
        }
    }

    fun setFavorite(fileId: String, on: Boolean) {
        val path = "/api/library/favorites/$fileId"
        send(path) { if (on) it.put(ByteArray(0).toRequestBody(null)) else it.delete() }.close()
    }

    // ------------------------------------------------------------------- media

    private var mediaToken: String? = null
    private var mediaTokenExpiresAt = 0L

    /** A short-lived, read-only token for thumbnail and content URLs (renewed before it expires). */
    @Synchronized
    fun mediaToken(): String {
        val now = System.currentTimeMillis()
        val cached = mediaToken
        if (cached != null && now < mediaTokenExpiresAt) return cached
        val body = send("/api/media/token") { it.post(ByteArray(0).toRequestBody(null)) }.jsonBody()
        val token = body.getString("token")
        mediaToken = token
        mediaTokenExpiresAt = now + body.optLong("expires_in", 3600) * 700 // renew at 70%
        return token
    }

    fun thumbnailUrl(fileId: String, size: Int = 256): String =
        "$base/api/media/${mediaToken()}/$fileId/thumbnail?size=$size"

    /** Makes a public link to one file and returns its full address. */
    fun createShareLink(fileId: String, expiresInHours: Int?, maxDownloads: Int?): String {
        val request = JSONObject().put("file_id", fileId)
        expiresInHours?.let { request.put("expires_in_hours", it) }
        maxDownloads?.let { request.put("max_downloads", it) }
        val body = send("/api/shares") { it.post(json(request)) }.jsonBody()
        // A configured public address (PUBLIC_BASE_URL) is what outsiders can reach.
        // optString returns the TEXT "null" for a JSON null, which is how links ended up reading "null".
        val publicUrl = if (body.isNull("public_url")) "" else body.optString("public_url")
        return publicUrl.ifBlank { base + body.getString("url_path") }
    }

    fun contentUrl(fileId: String): String = "$base/api/media/${mediaToken()}/$fileId/content"

    /**
     * Downloads a file's bytes to `dest` (at most `maxBytes`), reporting progress. The bytes
     * come through the media route, so no token is ever sent as a header.
     */
    fun downloadContent(
        fileId: String,
        dest: java.io.File,
        maxBytes: Long = Long.MAX_VALUE,
        onProgress: (done: Long, total: Long) -> Unit = { _, _ -> },
    ): Long {
        val url = contentUrl(fileId)
        val request = Request.Builder().url(url).apply {
            if (maxBytes != Long.MAX_VALUE) header("Range", "bytes=0-${maxBytes - 1}")
        }.build()
        log("-> GET /api/media/<token>/$fileId/content")
        val response = try {
            http.newCall(request).execute()
        } catch (e: IOException) {
            log("!! download network error: ${e.message}")
            throw ApiUnavailable(e.message ?: e.javaClass.simpleName)
        }
        response.use {
            log("<- ${it.code} GET content for $fileId")
            if (it.code >= 400) throw ApiError(it.code, "could not download the file (${it.code})")
            val total = it.body!!.contentLength()
            var done = 0L
            dest.parentFile?.mkdirs()
            it.body!!.byteStream().use { input ->
                dest.outputStream().use { out ->
                    val buffer = ByteArray(64 * 1024)
                    while (true) {
                        val read = input.read(buffer)
                        if (read < 0) break
                        out.write(buffer, 0, read)
                        done += read
                        onProgress(done, total)
                    }
                }
            }
            return done
        }
    }
}
