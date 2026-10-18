package cloud.personal.sync

import android.Manifest
import android.content.ContentUris
import android.content.Context
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.MediaStore

/**
 * The photos and videos on the phone itself, shown in the timeline next to the server's so you see
 * everything in one place, including what has not been backed up yet. Only the folders chosen for
 * backup are listed, and anything the server already has (same name and size) is left out so nothing
 * appears twice.
 */
object LocalMedia {
    fun canRead(context: Context): Boolean =
        if (Build.VERSION.SDK_INT >= 33) {
            context.checkSelfPermission(Manifest.permission.READ_MEDIA_IMAGES) == PackageManager.PERMISSION_GRANTED
        } else {
            context.checkSelfPermission(Manifest.permission.READ_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED
        }

    /** Pure rule, unit tested: which phone photos the server does not have yet. */
    fun notOnServer(local: List<RemoteItem>, server: List<RemoteItem>): List<RemoteItem> {
        val have = HashSet<String>(server.size * 2)
        for (item in server) have.add(key(item.name, item.size))
        return local.filter { key(it.name, it.size) !in have }
    }

    private fun key(name: String, size: Long) = "${name.lowercase()}|$size"

    fun scan(context: Context, folders: Set<String>): List<RemoteItem> {
        if (!canRead(context)) return emptyList()
        val out = ArrayList<RemoteItem>()
        for ((collection, takenColumn) in listOf(
            MediaStore.Images.Media.EXTERNAL_CONTENT_URI to MediaStore.Images.Media.DATE_TAKEN,
            MediaStore.Video.Media.EXTERNAL_CONTENT_URI to MediaStore.Video.Media.DATE_TAKEN,
        )) {
            val projection = arrayOf(
                MediaStore.MediaColumns._ID,
                MediaStore.MediaColumns.DISPLAY_NAME,
                MediaStore.MediaColumns.SIZE,
                MediaStore.MediaColumns.MIME_TYPE,
                MediaStore.MediaColumns.RELATIVE_PATH,
                MediaStore.MediaColumns.DATE_MODIFIED,
                takenColumn,
            )
            try {
                context.contentResolver.query(collection, projection, null, null, null)?.use { c ->
                    while (c.moveToNext()) {
                        val path = if (Build.VERSION.SDK_INT >= 29) c.getString(4) else null
                        if (folders.isNotEmpty() && !isSelected(path, folders)) continue
                        val taken = c.getLong(6)
                        val modified = c.getLong(5) * 1000
                        val uri: Uri = ContentUris.withAppendedId(collection, c.getLong(0))
                        out.add(
                            RemoteItem(
                                id = "local:${c.getLong(0)}",
                                name = c.getString(1) ?: "photo",
                                size = c.getLong(2),
                                mime = c.getString(3) ?: "",
                                favorite = false,
                                folderPath = path?.trimEnd('/') ?: "",
                                takenAtMillis = if (taken > 0) taken else null,
                                createdAtMillis = modified,
                                modifiedAtMillis = modified,
                                localUri = uri.toString(),
                            ),
                        )
                    }
                }
            } catch (e: SecurityException) {
                // permission was withdrawn: show the server's photos only
            } catch (e: Exception) {
                EventLog.log("local media scan failed: ${e.javaClass.simpleName}: ${e.message}")
            }
        }
        return out
    }
}
