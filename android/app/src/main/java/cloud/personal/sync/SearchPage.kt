package cloud.personal.sync

import android.os.Handler
import android.os.Looper
import android.text.Editable
import android.text.InputType
import android.text.TextWatcher
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.widget.EditText
import android.widget.LinearLayout
import kotlin.concurrent.thread

/**
 * Search by file name and by what is written inside documents. Types as you go (250 ms after the last
 * key), shows folders, files and "found inside" snippets; tapping a result opens it.
 */
class SearchPage(private val host: Host, private val openFolder: (id: String, name: String) -> Unit) {
    private val ui = host.ui
    private val palette = ui.palette
    private val handler = Handler(Looper.getMainLooper())
    private var latest = 0

    fun show() {
        val field = EditText(ui.context).apply {
            hint = "Search your files"
            inputType = InputType.TYPE_CLASS_TEXT
            imeOptions = EditorInfo.IME_ACTION_SEARCH
            typeface = ui.typeface
            setTextColor(palette.ink)
            setHintTextColor(palette.mute)
            textSize = 15f
            setSingleLine()
            setPadding(ui.dp(16), ui.dp(14), ui.dp(16), ui.dp(14))
            background = null
        }
        val header = ui.horizontal().apply {
            setBackgroundColor(palette.surface)
            addView(ui.icon(R.drawable.ic_search, 20, palette.mute).apply { (layoutParams as LinearLayout.LayoutParams).leftMargin = ui.dp(16) })
            addView(field, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        }
        val page = host.sheets.page("Search", header)
        val results = ui.vertical()
        page.body.addView(results)
        results.addView(hint("Type a name, or words from inside a document."))

        val run = Runnable { search(field.text.toString().trim(), page, results) }
        field.addTextChangedListener(object : TextWatcher {
            override fun afterTextChanged(s: Editable?) {
                handler.removeCallbacks(run)
                handler.postDelayed(run, 250)
            }
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
        })
        field.setOnEditorActionListener { _, _, _ ->
            handler.removeCallbacks(run)
            run.run()
            true
        }
        field.requestFocus()
        field.postDelayed({
            (ui.context.getSystemService(android.content.Context.INPUT_METHOD_SERVICE) as android.view.inputmethod.InputMethodManager)
                .showSoftInput(field, 0)
        }, 150)
    }

    private fun hint(text: String) = ui.muted(text, 13f).apply { setPadding(ui.dp(20), ui.dp(20), ui.dp(20), ui.dp(20)) }

    private fun search(query: String, page: Page, results: LinearLayout) {
        if (query.isEmpty()) {
            results.removeAllViews()
            results.addView(hint("Type a name, or words from inside a document."))
            return
        }
        val mine = ++latest
        results.removeAllViews()
        results.addView(hint("Searching..."))
        thread {
            try {
                val found = host.api.search(query)
                host.runOnUi {
                    if (mine != latest || !page.isShowing) return@runOnUi
                    show(found, page, results)
                }
            } catch (e: Exception) {
                EventLog.log("search failed: ${e.javaClass.simpleName}: ${e.message}")
                host.runOnUi {
                    if (mine != latest || !page.isShowing) return@runOnUi
                    results.removeAllViews()
                    results.addView(hint("Search failed: ${e.message}"))
                }
            }
        }
    }

    private fun show(found: ApiClient.SearchResults, page: Page, results: LinearLayout) {
        results.removeAllViews()
        if (found.folders.isEmpty() && found.files.isEmpty() && found.inside.isEmpty()) {
            results.addView(hint("Nothing found."))
            return
        }
        val side = ui.matchWidth().apply { setMargins(ui.dp(16), 0, ui.dp(16), 0) }
        if (found.folders.isNotEmpty()) {
            results.addView(ui.sectionHeader("Folders"))
            results.addView(
                ui.group(
                    *found.folders.map { f ->
                        ui.listRow(R.drawable.ic_folder, f.name) {
                            page.dismiss()
                            openFolder(f.id, f.name)
                        } as View
                    }.toTypedArray(),
                ),
                side,
            )
        }
        if (found.files.isNotEmpty()) {
            results.addView(ui.sectionHeader("Files"))
            results.addView(
                ui.group(
                    *found.files.mapIndexed { index, file ->
                        ui.listRow(null, file.name, listOf(file.folderPath.ifEmpty { "My files" }, fmtBytes(file.size)).joinToString("  |  ")) {
                            host.openViewer(found.files, index)
                        } as View
                    }.toTypedArray(),
                ),
                side,
            )
        }
        if (found.inside.isNotEmpty()) {
            results.addView(ui.sectionHeader("Found inside documents"))
            val files = found.inside.map { it.first }
            results.addView(
                ui.group(
                    *found.inside.mapIndexed { index, (file, snippet) ->
                        ui.listRow(null, file.name, snippet.replace('\n', ' ').take(120)) {
                            host.openViewer(files, index)
                        } as View
                    }.toTypedArray(),
                ),
                side,
            )
        }
        results.addView(ui.spacer(24))
    }
}
