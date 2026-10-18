package cloud.personal.sync

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import java.time.LocalDate
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread

/**
 * Uploads files the person picks (or shares into Choud from another app) into a chosen folder.
 * A name that is already taken is never overwritten: the new file keeps both by getting a dated name.
 */
object PhoneUpload {
    class Picked(val uri: Uri, val name: String, val size: Long, val mime: String)

    fun describe(context: Context, uri: Uri): Picked {
        var name = "file"
        var size = -1L
        context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { c ->
            if (c.moveToFirst()) {
                c.getString(0)?.let { name = it }
                if (!c.isNull(1)) size = c.getLong(1)
            }
        }
        if (size < 0) {
            size = try {
                context.contentResolver.openAssetFileDescriptor(uri, "r")?.use { it.length } ?: 0L
            } catch (e: Exception) {
                0L
            }
        }
        val mime = context.contentResolver.getType(uri) ?: "application/octet-stream"
        return Picked(uri, safeFileName(name), size, mime)
    }

    /** Reports "n of m" through the toast while it works and the result at the end. Runs in the background. */
    fun upload(host: Host, folderId: String?, uris: List<Uri>, onDone: (ok: Int, failed: Int) -> Unit) {
        if (uris.isEmpty()) return
        val context = host.ui.context
        val api = host.api
        thread {
            val ok = AtomicInteger()
            var failed = 0
            uris.forEachIndexed { index, uri ->
                val picked = describe(context, uri)
                host.runOnUi { host.toast("Uploading ${index + 1} of ${uris.size}: ${picked.name}") }
                try {
                    val open = { context.contentResolver.openInputStream(uri) ?: throw java.io.IOException("cannot open ${picked.name}") }
                    val hash = if (picked.size > CHUNKED_THRESHOLD) sha256Hex(open) else ""
                    try {
                        api.uploadNew(open, picked.name, folderId, picked.size, picked.mime, hash)
                    } catch (e: VersionConflict) {
                        api.uploadNew(open, conflictName(picked.name, LocalDate.now().toString()), folderId, picked.size, picked.mime, hash)
                    }
                    ok.incrementAndGet()
                } catch (e: Exception) {
                    failed++
                    EventLog.log("phone upload failed for ${picked.name}: ${e.javaClass.simpleName}: ${e.message}")
                }
            }
            ListCache.clear()
            host.runOnUi {
                host.toast(if (failed == 0) "Uploaded ${ok.get()} file${if (ok.get() == 1) "" else "s"}." else "${ok.get()} uploaded, $failed failed.")
                onDone(ok.get(), failed)
            }
        }
    }
}
