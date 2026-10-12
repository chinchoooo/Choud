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

/** A request body that re-opens its source each time, so a retry after a token refresh works. */
private class StreamBody(
    private val open: () -> InputStream,
    private val offset: Long,
    private val length: Long,
    private val type: String,
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
            }
        }
    }
}

fun sha256Hex(open: () -> InputStream): String {
    val digest = MessageDigest.getInstance("SHA-256")
    open().use { stream ->
        val buffer = ByteArray(64 * 1024)
        while (true) {
            val read = stream.read(buffer)
            if (read < 0) break
            digest.update(buffer, 0, read)
        }
    }
    return digest.digest().joinToString("") { "%02x".format(it) }
}

/** HTTP client for the Personal Cloud API; port of client/cloudsync/api.py (the reference). */
class ApiClient(
    baseUrl: String,
    private val tokens: TokenStore,
    private val http: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(300, TimeUnit.SECONDS)
        .writeTimeout(300, TimeUnit.SECONDS)
        .build(),
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

    private fun raiseForError(response: Response) {
        if (response.code < 400) return
        val raw = response.body?.string().orEmpty()
        val text = detailText(raw, response.message)
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
        val builder = Request.Builder().url(base + path)
        if (tokens.access.isNotEmpty()) builder.header("Authorization", "Bearer ${tokens.access}")
        val response = try {
            http.newCall(build(builder).build()).execute()
        } catch (e: IOException) {
            throw ApiUnavailable(e.message ?: e.javaClass.simpleName)
        }
        if (response.code == 401 && retryAuth && tokens.refresh.isNotEmpty() && !path.startsWith("/api/auth/")) {
            response.close()
            refresh()
            return send(path, false, build)
        }
        try {
            raiseForError(response)
        } finally {
            if (response.code >= 400) response.close()
        }
        return response
    }

    private fun json(obj: JSONObject): RequestBody =
        obj.toString().toRequestBody("application/json".toMediaType())

    private fun Response.jsonBody(): JSONObject = use { JSONObject(it.body!!.string()) }

    fun login(email: String, password: String) {
        val body = send("/api/auth/login", false) {
            it.post(json(JSONObject().put("email", email).put("password", password)))
        }.jsonBody()
        tokens.access = body.getString("access_token")
        tokens.refresh = body.getString("refresh_token")
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
    }

    /** Remote files by path. An unchanged tree is a bodyless 304 (cheap on mobile data). */
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
    ): UploadResult =
        if (size <= CHUNKED_THRESHOLD) uploadSmall(open, name, folderId, size, mime)
        else uploadChunked(open, name, folderId, size, contentHash, resumeId, onSession)

    private fun result(body: JSONObject) =
        UploadResult(body.getString("id"), body.optString("content_hash", ""))

    private fun uploadSmall(
        open: () -> InputStream, name: String, folderId: String, size: Long, mime: String,
    ): UploadResult =
        result(
            send("/api/files/upload") {
                val form = MultipartBody.Builder().setType(MultipartBody.FORM)
                    .addFormDataPart("name", name)
                    .addFormDataPart("folder_id", folderId)
                    .addFormDataPart("base_version_id", "none")
                    .addFormDataPart("file", name, StreamBody(open, 0, size, mime))
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
            val created = send("/api/uploads") { it.post(json(payload)) }.jsonBody()
            session = send("/api/uploads/${created.getString("id")}").jsonBody()
            onSession(session.getString("id"))
        }
        val uploadId = session.getString("id")
        val chunkBytes = session.getLong("chunk_size")
        val missing = session.getJSONArray("missing_chunk_indices")
        for (i in 0 until missing.length()) {
            val index = missing.getInt(i)
            val offset = index * chunkBytes
            val length = minOf(chunkBytes, size - offset)
            send("/api/uploads/$uploadId/chunks/$index") {
                val form = MultipartBody.Builder().setType(MultipartBody.FORM)
                    .addFormDataPart(
                        "chunk", "chunk",
                        StreamBody(open, offset, length, "application/octet-stream"),
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
}
