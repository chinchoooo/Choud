package cloud.personal.sync

import android.content.ContentResolver
import android.content.ContentUris
import android.content.Context
import android.net.Uri
import android.provider.MediaStore
import java.time.LocalDate

data class BackupSummary(val uploaded: Int, val skipped: Int, val failed: Int)

data class MediaItem(
    val key: String,
    val uri: Uri,
    val name: String,
    val size: Long,
    val mime: String,
    val relativePath: String?,
)

/**
 * One-way camera-roll backup (phone -> server). It never downloads into the camera roll and
 * never deletes anything on the phone (docs/mobile.md, problem 1).
 */
class CameraBackup(
    private val context: Context,
    private val settings: Settings,
    private val db: BackupDb,
    private val api: ApiClient,
) {
    private val folderIds = HashMap<String, String>()

    private fun query(collection: Uri, prefix: String): List<MediaItem> {
        val projection = arrayOf(
            MediaStore.MediaColumns._ID,
            MediaStore.MediaColumns.DISPLAY_NAME,
            MediaStore.MediaColumns.SIZE,
            MediaStore.MediaColumns.MIME_TYPE,
            MediaStore.MediaColumns.RELATIVE_PATH,
        )
        val items = ArrayList<MediaItem>()
        context.contentResolver.query(
            collection, projection,
            "${MediaStore.MediaColumns.RELATIVE_PATH} LIKE ?", arrayOf("DCIM/%"),
            "${MediaStore.MediaColumns.DATE_ADDED} ASC",
        )?.use { c ->
            while (c.moveToNext()) {
                val id = c.getLong(0)
                items += MediaItem(
                    key = "$prefix:$id",
                    uri = ContentUris.withAppendedId(collection, id),
                    name = safeFileName(c.getString(1) ?: "$prefix$id"),
                    size = c.getLong(2),
                    mime = c.getString(3) ?: "application/octet-stream",
                    relativePath = c.getString(4),
                )
            }
        }
        return items
    }

    /** How many camera-roll files the app can see (0 with a permission problem). */
    fun visibleCount(): Int = listOf(
        MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
        MediaStore.Video.Media.EXTERNAL_CONTENT_URI,
    ).sumOf { uri ->
        context.contentResolver.query(
            uri, arrayOf(MediaStore.MediaColumns._ID),
            "${MediaStore.MediaColumns.RELATIVE_PATH} LIKE ?", arrayOf("DCIM/%"), null,
        )?.use { it.count } ?: 0
    }

    fun pending(): List<MediaItem> =
        (query(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, "i") +
            query(MediaStore.Video.Media.EXTERNAL_CONTENT_URI, "v"))
            .filter { db.status(it.key) != "done" }

    /** Backs up everything not yet backed up. Throws ApiUnavailable / AuthError to stop the run. */
    fun run(onProgress: (done: Int, total: Int, name: String) -> Unit = { _, _, _ -> }): BackupSummary {
        val items = pending()
        var uploaded = 0
        var failed = 0
        items.forEachIndexed { index, item ->
            onProgress(index, items.size, item.name)
            try {
                backUp(item)
                uploaded++
            } catch (e: ApiError) {
                if (e is AuthError || e.transient) throw e
                db.set(item.key, "failed", error = e.message)
                failed++
            } catch (e: java.io.IOException) {
                if (e is ApiUnavailable) throw e
                // Unreadable or vanished file: record it, keep going.
                db.set(item.key, "failed", error = e.message)
                failed++
            }
        }
        return BackupSummary(uploaded, 0, failed)
    }

    private fun open(resolver: ContentResolver, uri: Uri) = {
        resolver.openInputStream(uri) ?: throw java.io.IOException("cannot open $uri")
    }

    private fun backUp(item: MediaItem) {
        val resolver = context.contentResolver
        val opener = open(resolver, item.uri)
        val folder = remoteFolderFor(settings.deviceName, item.relativePath)
        val folderId = folderIds.getOrPut(folder) { api.ensureFolder(folder) }
        val size = resolver.openAssetFileDescriptor(item.uri, "r")?.use { it.length } ?: item.size
        val hash = sha256Hex(opener)

        fun attempt(name: String): String? = try {
            api.uploadNew(
                opener, name, folderId, size, item.mime, hash,
                resumeId = db.uploadId(item.key),
                onSession = { id -> db.set(item.key, "uploading", uploadId = id) },
            )
            "$folder/$name"
        } catch (e: VersionConflict) {
            null
        }

        var remote = attempt(item.name)
        if (remote == null) {
            // Name taken. Same bytes = already backed up (e.g. after a reinstall); different
            // bytes = keep both, as a conflict copy. Nothing is ever overwritten.
            if (api.snapshot()["$folder/${item.name}"]?.contentHash == hash) {
                remote = "$folder/${item.name}"
            } else {
                val copy = conflictName(item.name, LocalDate.now().toString())
                remote = attempt(copy)
                    ?: if (api.snapshot()["$folder/$copy"]?.contentHash == hash) "$folder/$copy"
                    else throw ApiError(409, "name clash for ${item.name}")
            }
        }
        db.set(item.key, "done", remotePath = remote)
    }
}
