package cloud.personal.sync

import android.content.Context
import android.content.Intent
import androidx.core.content.FileProvider
import java.io.File
import kotlin.concurrent.thread

/**
 * Sends the files themselves to another app (messages, mail, a chat) when a link would not help,
 * for example because the server has no public address. Files are copied into the app's cache
 * folder that the FileProvider is allowed to share, then handed over with the system share sheet.
 */
object FileSender {
    fun send(context: Context, api: ApiClient, files: List<RemoteItem>, runOnUi: (() -> Unit) -> Unit, say: (String) -> Unit) {
        if (files.isEmpty()) return
        say(if (files.size == 1) "Preparing ${files[0].name}..." else "Preparing ${files.size} files...")
        thread {
            val dir = File(context.cacheDir, "viewer").apply { mkdirs() }
            try {
                val targets = files.map { file ->
                    val target = File(dir, "send-${file.id}-${file.name.replace('/', '_')}")
                    val kept = OfflineStore.file(context, file.id)
                    if (kept != null) kept.copyTo(target, overwrite = true) else api.downloadContent(file.id, target)
                    file to target
                }
                runOnUi {
                    val uris = ArrayList(targets.map { (_, f) -> FileProvider.getUriForFile(context, "${context.packageName}.files", f) })
                    val intent = if (uris.size == 1) {
                        Intent(Intent.ACTION_SEND).apply {
                            type = targets[0].first.mime.ifEmpty { "*/*" }
                            putExtra(Intent.EXTRA_STREAM, uris[0])
                        }
                    } else {
                        Intent(Intent.ACTION_SEND_MULTIPLE).apply {
                            type = "*/*"
                            putParcelableArrayListExtra(Intent.EXTRA_STREAM, uris)
                        }
                    }
                    intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    context.startActivity(Intent.createChooser(intent, "Send").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                }
            } catch (e: Exception) {
                EventLog.log("send files failed: ${e.javaClass.simpleName}: ${e.message}")
                runOnUi { say("Could not prepare the file: ${e.message}") }
            }
        }
    }
}
