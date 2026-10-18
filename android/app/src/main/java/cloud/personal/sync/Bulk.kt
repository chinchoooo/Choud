package cloud.personal.sync

import android.content.ClipData
import android.content.ClipboardManager
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import java.io.File
import java.time.LocalDate
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread

/** Saves a downloaded file where the person can find it: the phone's Downloads folder. */
object Saver {
    /** Returns a short description of where it went. Moves nothing: `source` is copied. */
    fun save(context: Context, source: File, name: String, mime: String): String {
        if (Build.VERSION.SDK_INT >= 29) {
            val resolver = context.contentResolver
            val values = ContentValues().apply {
                put(MediaStore.Downloads.DISPLAY_NAME, name)
                put(MediaStore.Downloads.MIME_TYPE, mime)
                put(MediaStore.Downloads.RELATIVE_PATH, "${Environment.DIRECTORY_DOWNLOADS}/Choud")
                put(MediaStore.Downloads.IS_PENDING, 1)
            }
            val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                ?: throw java.io.IOException("could not create the file in Downloads")
            try {
                resolver.openOutputStream(uri)!!.use { out -> source.inputStream().use { it.copyTo(out) } }
                resolver.update(uri, ContentValues().apply { put(MediaStore.Downloads.IS_PENDING, 0) }, null, null)
            } catch (e: Exception) {
                resolver.delete(uri, null, null)
                throw e
            }
            return "Downloads/Choud"
        }
        // Older phones: the app's own downloads folder (no storage permission needed).
        val dir = context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS) ?: context.filesDir
        dir.mkdirs()
        var target = File(dir, name)
        var n = 2
        while (target.exists()) target = File(dir, "${name.substringBeforeLast('.')} ($n).${name.substringAfterLast('.', "")}".trimEnd('.')).also { n++ }
        source.copyTo(target)
        return target.parent ?: "Downloads"
    }
}

/** A pick-a-folder dialog: browse the server's folders, then "Move here". */
class FolderPickerDialog(
    private val host: Host,
    private val context: Context,
    private val title: String,
    private val excluded: Set<String>,
    private val onPick: (folderId: String?, name: String) -> Unit,
) {
    private val ui = host.ui
    private val trail = ArrayList<Pair<String?, String>>().apply { add(null to "My files") }
    private lateinit var sheet: SheetHandle
    private val body = ui.vertical()

    fun show() {
        sheet = host.sheets.show(title) { handle ->
            handle.body.addView(body)
            handle.body.addView(
                host.sheets.buttons(handle, "Move here") { onPick(trail.last().first, trail.last().second) },
                LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = ui.dp(8) },
            )
        }
        load()
    }

    private fun load() {
        body.removeAllViews()
        body.addView(ui.muted(trail.joinToString("  /  ") { it.second }, 12f).apply { setPadding(ui.dp(20), ui.dp(8), ui.dp(20), ui.dp(8)) })
        body.addView(ui.muted("Loading...", 13f).apply { setPadding(ui.dp(20), ui.dp(8), ui.dp(20), ui.dp(8)) })
        val folder = trail.last().first
        thread {
            val folders = try { host.api.listDirectory(folder).folders } catch (e: Exception) { null }
            host.runOnUi {
                if (!sheet.isShowing) return@runOnUi
                body.removeViewAt(body.childCount - 1)
                if (folders == null) {
                    body.addView(ui.text("Could not load folders.", 13f, ui.palette.danger).apply { setPadding(ui.dp(20), ui.dp(8), ui.dp(20), ui.dp(8)) })
                    return@runOnUi
                }
                if (trail.size > 1) body.addView(row("..  (up one level)") { trail.removeAt(trail.lastIndex); load() })
                val shown = folders.filter { it.id !in excluded }
                if (shown.isEmpty()) body.addView(ui.muted("No folders here.", 13f).apply { setPadding(ui.dp(20), ui.dp(8), ui.dp(20), ui.dp(8)) })
                shown.forEach { f -> body.addView(row(f.name) { trail.add(f.id to f.name); load() }) }
            }
        }
    }

    private fun row(label: String, onClick: () -> Unit): View = ui.horizontal().apply {
        setPadding(ui.dp(20), ui.dp(12), ui.dp(20), ui.dp(12))
        isClickable = true
        addView(ui.icon(R.drawable.ic_nav_files, 20, ui.palette.mute))
        addView(ui.text(label, 14f).apply { setPadding(ui.dp(12), 0, 0, 0) })
        setOnClickListener { onClick() }
        layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
    }
}

/**
 * Everything you can do to a selection of files and folders. Each action runs in the background,
 * reports progress as it goes and says exactly how many worked, so one failure never hides the rest.
 */
class Bulk(private val host: Host, private val context: Context) {
    private val api get() = host.api

    private fun say(text: String, action: String? = null, onAction: (() -> Unit)? = null) =
        host.runOnUi { host.toast(text, action, onAction) }

    /** Runs `job` for every item; reports "label: x of n" while working and the result at the end. */
    private fun <T> each(label: String, items: List<T>, onFinish: (ok: Int, failed: Int) -> Unit, job: (T) -> Unit) {
        thread {
            val ok = AtomicInteger()
            var failed = 0
            items.forEachIndexed { index, item ->
                say("$label ${index + 1} of ${items.size}...")
                try {
                    job(item)
                    ok.incrementAndGet()
                } catch (e: Exception) {
                    failed++
                    EventLog.log("bulk $label failed: ${e.javaClass.simpleName}: ${e.message}")
                }
            }
            host.runOnUi { onFinish(ok.get(), failed) }
        }
    }

    // ------------------------------------------------------------------ share

    fun shareLinks(files: List<RemoteItem>) {
        if (files.isEmpty()) return
        host.sheets.linkChoices("Share ${files.size} file${if (files.size == 1) "" else "s"}") { hours, limit ->
            val lines = java.util.Collections.synchronizedList(ArrayList<String>())
            each("Making link", files, { ok, failed ->
                if (lines.isEmpty()) {
                    host.toast("Could not make links.")
                    return@each
                }
                val text = if (files.size == 1) lines.first().substringAfter(": ") else lines.joinToString("\n")
                val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                clipboard.setPrimaryClip(ClipData.newPlainText("Choud links", text))
                host.toast(
                    if (failed == 0) "$ok link${if (ok == 1) "" else "s"} copied." else "$ok copied, $failed failed.",
                    "Send",
                ) {
                    val send = Intent(Intent.ACTION_SEND).apply { type = "text/plain"; putExtra(Intent.EXTRA_TEXT, text) }
                    context.startActivity(Intent.createChooser(send, "Send links").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                }
            }) { file -> lines.add("${file.name}: ${api.createShareLink(file.id, hours, limit)}") }
        }
    }

    // --------------------------------------------------------------- download

    /** One file is saved as itself; several files or any folder are saved as one .zip. */
    fun download(files: List<RemoteItem>, folders: List<FolderItem>) {
        if (files.isEmpty() && folders.isEmpty()) return
        say(if (files.size == 1 && folders.isEmpty()) "Downloading ${files[0].name}..." else "Preparing a zip...")
        thread {
            val temp = File(context.cacheDir, "save/${System.nanoTime()}").apply { parentFile?.mkdirs() }
            try {
                val (name, mime) = if (files.size == 1 && folders.isEmpty()) {
                    api.downloadContent(files[0].id, temp)
                    files[0].name to files[0].mime.ifEmpty { "application/octet-stream" }
                } else {
                    api.downloadZip(files.map { it.id }, folders.map { it.id }, temp)
                    val label = if (folders.size == 1 && files.isEmpty()) folders[0].name else "Choud-${LocalDate.now()}"
                    "$label.zip" to "application/zip"
                }
                val where = Saver.save(context, temp, name, mime)
                say("Saved $name to $where.", "Open") {
                    runCatching {
                        context.startActivity(Intent(android.app.DownloadManager.ACTION_VIEW_DOWNLOADS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                    }
                }
            } catch (e: Exception) {
                EventLog.log("save failed: ${e.javaClass.simpleName}: ${e.message}")
                say("Could not save: ${e.message}")
            } finally {
                temp.delete()
            }
        }
    }

    // ---------------------------------------------------------------- offline

    fun keepOffline(files: List<RemoteItem>, onDone: () -> Unit) {
        val todo = files.filter { !OfflineStore.has(context, it.id) }
        if (todo.isEmpty()) {
            host.toast("Already on this phone.")
            return
        }
        each("Keeping", todo, { ok, failed ->
            host.toast(if (failed == 0) "$ok file${if (ok == 1) "" else "s"} kept on this phone." else "$ok kept, $failed failed.")
            onDone()
        }) { OfflineStore.keep(context, api, it) }
    }

    // --------------------------------------------------------------- favorite

    fun favorite(files: List<RemoteItem>, on: Boolean, onDone: () -> Unit) {
        each(if (on) "Starring" else "Unstarring", files, { ok, failed ->
            host.toast(if (failed == 0) "${if (on) "Starred" else "Unstarred"} $ok." else "$ok done, $failed failed.")
            onDone()
        }) { api.setFavorite(it.id, on) }
    }

    // ------------------------------------------------------------------- move

    fun move(files: List<RemoteItem>, folders: List<FolderItem>, onDone: () -> Unit) {
        FolderPickerDialog(host, context, "Move ${files.size + folders.size} item(s) to...", folders.map { it.id }.toSet()) { target, name ->
            val jobs: List<() -> Unit> = files.map { f -> { api.moveFile(f.id, target) } } + folders.map { f -> { api.moveFolder(f.id, target) } }
            each("Moving", jobs, { ok, failed ->
                host.toast(if (failed == 0) "Moved $ok to $name." else "$ok moved, $failed could not be (a name is already taken there).")
                onDone()
            }) { it() }
        }.show()
    }

    // ----------------------------------------------------------------- delete

    fun delete(files: List<RemoteItem>, folders: List<FolderItem>, onDone: () -> Unit) {
        val detail = buildString {
            if (files.isNotEmpty()) append("${files.size} file${if (files.size == 1) "" else "s"} will go to the trash (you can undo).")
            if (folders.isNotEmpty()) append("${if (isNotEmpty()) " " else ""}${folders.size} folder${if (folders.size == 1) "" else "s"} are removed only if empty.")
        }
        host.sheets.confirm("Delete the selection?", detail, "Delete", danger = true) {
            val removed = java.util.Collections.synchronizedList(ArrayList<String>())
            val jobs: List<() -> Unit> = files.map { f -> { api.deleteFile(f.id); removed.add(f.id); Unit } } + folders.map { f -> { api.deleteFolder(f.id) } }
            each("Deleting", jobs, { ok, failed ->
                val text = if (failed == 0) "Deleted $ok." else "$ok deleted, $failed could not be (a folder that is not empty)."
                if (removed.isNotEmpty()) {
                    host.toast(text, "Undo") {
                        thread {
                            removed.forEach { id -> runCatching { api.restoreFile(id) } }
                            host.runOnUi { host.toast("Restored."); onDone() }
                        }
                    }
                } else {
                    host.toast(text)
                }
                onDone()
            }) { it() }
        }
    }
}
