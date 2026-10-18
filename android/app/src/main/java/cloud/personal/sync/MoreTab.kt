package cloud.personal.sync

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings as AndroidSettings
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import kotlin.concurrent.thread

/**
 * The settings hub. The home page is a short list of rows; each row opens a screen of its own
 * (pushed on a small stack, popped by Back). Nothing here uses a stock widget.
 */
class MoreTab(private val host: Host, private val onLogout: () -> Unit) : Tab {
    private val ui = host.ui
    private val palette = ui.palette
    private val settings = host.settings

    private class Screen(val view: View, val onTick: () -> Unit = {})

    private val stack = ArrayList<Screen>()
    override val view = FrameLayout(ui.context).apply { setBackgroundColor(palette.bg) }

    // Home page pieces that update from the network.
    private val usageText = ui.muted("", 12f)
    private val usageBar = ui.bar()
    private var usageLoadedAt = 0L

    // Diagnostics
    private val factsView = ui.text("", 12f).apply { typeface = android.graphics.Typeface.MONOSPACE }
    private val logView = ui.text("", 11f).apply {
        typeface = android.graphics.Typeface.MONOSPACE
        setTextIsSelectable(true)
    }
    private var shownLogVersion = -1

    // Backup folders
    private val foldersBox = ui.vertical()
    private var foldersLoadedAt = 0L

    private var connectionResult: String? = null
    private var datesResult: String? = null
    private var homeRows: LinearLayout? = null

    init {
        showHome()
    }

    // ------------------------------------------------------------------ stack

    private fun display(screen: Screen) {
        view.removeAllViews()
        view.addView(screen.view, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
    }

    private fun setScreen(screen: Screen) {
        stack.add(screen)
        display(screen)
    }

    private fun push(title: String, onTick: () -> Unit = {}, build: (LinearLayout) -> Unit) {
        val column = ui.vertical().apply { setPadding(0, 0, 0, ui.dp(32)) }
        build(column)
        val page = ui.vertical().apply {
            addView(ui.topBar(title, onBack = { pop() }))
            addView(ui.divider())
            addView(ScrollView(ui.context).apply { addView(column) }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        }
        setScreen(Screen(page, onTick))
    }

    private fun pop() {
        if (stack.size <= 1) return
        stack.removeAt(stack.lastIndex)
        display(stack.last())
        stack.last().onTick()
        if (stack.size == 1) refreshHome()
    }

    override fun onBack(): Boolean {
        if (stack.size > 1) {
            pop()
            return true
        }
        return false
    }

    // ------------------------------------------------------------------- home

    private fun showHome() {
        stack.clear()
        val column = ui.vertical().apply { setPadding(0, 0, 0, ui.dp(32)) }
        column.addView(accountCard(), ui.matchWidth().apply { setMargins(ui.dp(16), ui.dp(16), ui.dp(16), 0) })
        homeRows = ui.vertical().also { column.addView(it) }
        buildHomeRows()
        setScreen(Screen(ScrollView(ui.context).apply { addView(column) }))
    }

    private fun accountCard(): View = ui.card().apply {
        addView(ui.text(settings.deviceName.ifEmpty { "This phone" }, 15f, bold = true))
        addView(ui.muted(settings.serverUrl, 12f), ui.matchWidth(2))
        addView(usageBar, ui.matchWidth(12))
        addView(usageText, ui.matchWidth(6))
    }

    private fun refreshHome() = buildHomeRows()

    private fun buildHomeRows() {
        val rows = homeRows ?: return
        rows.removeAllViews()
        val context = host.ui.context
        val theme = AppTheme.fromId(settings.theme)

        rows.addView(ui.sectionHeader("Look"))
        rows.addView(
            ui.group(
                ui.listRow(R.drawable.ic_palette, "Appearance", value = theme.label) { showAppearance() },
            ),
            full(),
        )

        rows.addView(ui.sectionHeader("Backup"))
        rows.addView(
            ui.group(
                ui.listRow(R.drawable.ic_folder, "Folders to back up", value = "${settings.backupFolders.size} chosen") { showFolders() },
                ui.switchRow(R.drawable.ic_wifi, "Wi-Fi only", "Applies to the hourly automatic run", settings.wifiOnly) { on ->
                    settings.wifiOnly = on
                    EventLog.log("setting: Wi-Fi only = $on")
                    SyncWorker.schedule(context, settings)
                },
                ui.switchRow(R.drawable.ic_battery, "Only while charging", null, settings.chargingOnly) { on ->
                    settings.chargingOnly = on
                    EventLog.log("setting: charging only = $on")
                    SyncWorker.schedule(context, settings)
                },
                ui.listRow(R.drawable.ic_battery, "Allow background running", "Stops Android pausing the backup to save battery") {
                    context.startActivity(
                        Intent(
                            AndroidSettings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                            Uri.parse("package:${context.packageName}"),
                        ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                    )
                },
            ),
            full(),
        )

        rows.addView(ui.sectionHeader("Photos and storage"))
        val keptCount = OfflineStore.items(context).size
        rows.addView(
            ui.group(
                ui.listRow(
                    R.drawable.ic_offline,
                    "Kept on this phone",
                    if (keptCount == 0) "Open a file, then Keep, to read it without the server" else "Open without the server",
                    value = if (keptCount == 0) "none" else "$keptCount, ${fmtBytes(OfflineStore.totalBytes(context))}",
                ) { showKept() },
                ui.listRow(
                    R.drawable.ic_calendar,
                    "Fix dates of uploaded photos",
                    datesResult ?: "Gives undated photos the date in their name or EXIF",
                ) { fixDates() },
            ),
            full(),
        )

        rows.addView(ui.sectionHeader("Connection"))
        rows.addView(
            ui.group(
                ui.listRow(R.drawable.ic_link, "Server addresses", value = if (settings.altServerUrl.isBlank()) "one" else "two") { showAddresses() },
                ui.listRow(R.drawable.ic_wifi, "Test connection", connectionResult ?: "Checks that the server answers, and how fast") { testConnection() },
            ),
            full(),
        )

        rows.addView(ui.sectionHeader("About"))
        rows.addView(
            ui.group(
                ui.listRow(R.drawable.ic_activity, "Diagnostics", "Status, activity log, copy for support") { showDiagnostics() },
                ui.listRow(R.drawable.ic_info, "Version", value = appVersion(context), chevron = false),
                ui.listRow(R.drawable.ic_logout, "Log out", danger = true, chevron = false) {
                    host.sheets.confirm("Log out?", "Backups stop until you log in again. Files already on the server stay there.", "Log out", danger = true) { onLogout() }
                },
            ),
            full(),
        )
    }

    private fun full() = ui.matchWidth().apply { setMargins(ui.dp(16), 0, ui.dp(16), 0) }

    private fun appVersion(context: Context): String =
        runCatching { context.packageManager.getPackageInfo(context.packageName, 0).versionName }.getOrNull() ?: "?"

    // ------------------------------------------------------------ appearance

    private fun showAppearance() = push("Appearance") { column ->
        column.addView(ui.sectionHeader("Theme"))
        val rows = AppTheme.entries.map { theme ->
            ui.choiceRow(theme.label, selected = settings.theme == theme.id) {
                if (settings.theme != theme.id) {
                    settings.theme = theme.id
                    host.onThemeChanged()
                }
            }
        }
        column.addView(ui.group(*rows.toTypedArray()), full())
    }

    // --------------------------------------------------------------- folders

    private fun showFolders() = push("Folders to back up") { column ->
        column.addView(ui.muted("Changes apply to the next run. The camera roll is on by default.", 12f).apply {
            setPadding(ui.dp(20), ui.dp(14), ui.dp(20), ui.dp(4))
        })
        foldersBox.removeAllViews()
        (foldersBox.parent as? ViewGroup)?.removeView(foldersBox)
        column.addView(foldersBox, full())
        foldersBox.addView(ui.muted("Looking for folders...", 12f).apply { setPadding(ui.dp(16), ui.dp(16), ui.dp(16), ui.dp(16)) })
        foldersLoadedAt = 0
        loadFolders()
    }

    /** Lists every folder holding photos or videos as switches. */
    private fun loadFolders() {
        val now = System.currentTimeMillis()
        if (now - foldersLoadedAt < 30_000) return
        foldersLoadedAt = now
        thread {
            val found = try {
                val db = BackupDb(host.ui.context)
                try {
                    CameraBackup(host.ui.context, settings, db, host.api).discoverFolders()
                } finally {
                    db.close()
                }
            } catch (e: SecurityException) {
                null
            } catch (e: Exception) {
                EventLog.log("folder scan failed: ${e.javaClass.simpleName}: ${e.message}")
                null
            }
            host.runOnUi {
                foldersBox.removeAllViews()
                if (found == null) {
                    foldersBox.addView(emptyNote("Allow access to photos and videos to see your folders."))
                    return@runOnUi
                }
                if (found.isEmpty()) {
                    foldersBox.addView(emptyNote("No photos or videos found on this phone."))
                    return@runOnUi
                }
                val rows = found.map { (folder, count) ->
                    ui.switchRow(
                        R.drawable.ic_folder,
                        folder.trimEnd('/'),
                        "$count item${if (count == 1) "" else "s"}",
                        isSelected(folder, settings.backupFolders),
                    ) { on -> toggleFolder(folder, on, found.map { it.first }) }
                }
                foldersBox.addView(ui.group(*rows.toTypedArray()))
            }
        }
    }

    private fun emptyNote(text: String) = ui.muted(text, 13f).apply { setPadding(ui.dp(20), ui.dp(16), ui.dp(20), ui.dp(16)) }

    private fun toggleFolder(folder: String, on: Boolean, all: List<String>) {
        val chosen = settings.backupFolders.toMutableSet()
        // A folder inside an already-chosen parent (e.g. DCIM/Camera under DCIM/) is covered by
        // the parent, so unticking it means narrowing the parent.
        chosen.removeAll { it.startsWith(folder) && it != folder }
        if (on) {
            chosen.add(folder)
        } else {
            chosen.remove(folder)
            val parents = chosen.filter { folder.startsWith(it) }
            if (parents.isNotEmpty()) {
                chosen.removeAll(parents.toSet())
                for (other in all) {
                    if (other != folder && parents.any { other.startsWith(it) }) chosen.add(other)
                }
            }
        }
        settings.backupFolders = chosen
        EventLog.log("setting: backup folders = ${chosen.sorted()}")
        foldersLoadedAt = 0 // redraw so overlapping folders switch together
        loadFolders()
    }

    // ------------------------------------------------------------------ kept

    private fun showKept() {
        val context = host.ui.context
        val count = OfflineStore.items(context).size
        if (count == 0) {
            host.sheets.show("Kept on this phone") { sheet ->
                sheet.body.addView(
                    ui.muted(
                        "Nothing is kept yet. Open a file and choose Keep to read it without the server.",
                        13f,
                    ).apply { setPadding(ui.dp(20), 0, ui.dp(20), ui.dp(12)) },
                )
            }
            return
        }
        host.sheets.actions(
            "Kept on this phone",
            "$count file${if (count == 1) "" else "s"}, ${fmtBytes(OfflineStore.totalBytes(context))}",
            listOf(
                SheetItem(R.drawable.ic_delete, "Remove all kept files", danger = true) {
                    OfflineStore.clear(context)
                    host.toast("Removed.")
                    refreshHome()
                },
            ),
        )
    }

    // ----------------------------------------------------------- addresses

    private fun showAddresses() = push("Server addresses") { column ->
        column.addView(ui.muted(
            "The app tries the first address, then the second if the first does not answer. " +
                "Log out and in again to change them.",
            12f,
        ).apply { setPadding(ui.dp(20), ui.dp(14), ui.dp(20), ui.dp(4)) })
        val rows = mutableListOf<View>(ui.listRow(R.drawable.ic_wifi, "Main address", settings.serverUrl, chevron = false))
        if (settings.altServerUrl.isNotBlank()) {
            rows.add(ui.listRow(R.drawable.ic_link, "Away address", settings.altServerUrl, chevron = false))
        }
        column.addView(ui.group(*rows.toTypedArray()), full())
    }

    // ------------------------------------------------------------ diagnostics

    private fun showDiagnostics() {
        shownLogVersion = -1
        push("Diagnostics", onTick = { updateDiagnostics() }) { column ->
            column.addView(ui.sectionHeader("Status"))
            column.addView(ui.card().apply { addView(factsView) }, full())
            column.addView(ui.sectionHeader("Activity log"))
            column.addView(
                ui.horizontal().apply {
                    addView(ui.button("Copy log") {
                        val clip = host.ui.context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                        clip.setPrimaryClip(ClipData.newPlainText("Choud log", EventLog.tail(200_000)))
                        host.toast("Log copied.")
                    })
                    addView(View(ui.context), LinearLayout.LayoutParams(ui.dp(8), 1))
                    addView(ui.button("Clear log") {
                        EventLog.clear()
                        updateDiagnostics()
                    })
                },
                full(),
            )
            column.addView(ui.card().apply { addView(logView) }, full().apply { topMargin = ui.dp(8) })
        }
        updateDiagnostics()
    }

    private fun updateDiagnostics() {
        val f = host.facts
        factsView.text = buildString {
            appendLine("Photos     ${f.visible} visible | ${f.done} backed up | ${f.failed} failed")
            appendLine("Network    ${f.network}")
            appendLine("Power      ${f.power}")
            appendLine("Battery    exemption ${if (f.batteryExempt) "granted" else "NOT granted"}")
            appendLine("Perms      ${f.permissions}")
            appendLine("Job now    ${f.jobNow}")
            appendLine("Job hourly ${f.jobHourly}")
            appendLine("Last run   ${f.lastRun}")
            if (f.lastError.isNotEmpty()) appendLine("PROBLEM    ${f.lastError}")
        }.trimEnd()
        if (EventLog.version != shownLogVersion) {
            shownLogVersion = EventLog.version
            logView.text = EventLog.tail(8000)
        }
    }

    // ---------------------------------------------------------------- actions

    /** Asks the server to give undated photos the date in their name or EXIF, then reports. */
    private fun fixDates() {
        datesResult = "Reading dates from file names and EXIF..."
        refreshHome()
        thread {
            val result = try {
                val (fixed, checked) = host.api.fixDates(apply = true)
                if (checked == 0) "Every photo already has a date." else "Fixed the dates of $fixed of $checked undated photos."
            } catch (e: Exception) {
                EventLog.log("fix dates failed: ${e.javaClass.simpleName}: ${e.message}")
                "Could not fix dates: ${e.message}"
            }
            host.runOnUi {
                datesResult = result
                host.toast(result)
                if (stack.size == 1) refreshHome()
            }
        }
    }

    private fun testConnection() {
        connectionResult = "Testing..."
        refreshHome()
        val started = System.nanoTime()
        thread {
            val result = try {
                host.api.health()
                "OK in ${(System.nanoTime() - started) / 1_000_000} ms"
            } catch (e: Exception) {
                "Failed: ${e.javaClass.simpleName}: ${e.message}"
            }
            EventLog.log("connection test -> $result")
            host.runOnUi {
                connectionResult = result
                if (stack.size == 1) refreshHome()
            }
        }
    }

    // ------------------------------------------------------------------ usage

    override fun onShow() {
        loadUsage()
        if (stack.size == 1) refreshHome()
    }

    private fun loadUsage() {
        val now = System.currentTimeMillis()
        if (now - usageLoadedAt < 30_000) return
        usageLoadedAt = now
        thread {
            try {
                val usage = host.api.usage()
                host.runOnUi {
                    usageBar.progress = if (usage.quotaBytes > 0) usage.usedBytes.toFloat() / usage.quotaBytes else 0f
                    usageText.text = "${fmtBytes(usage.usedBytes)} of ${fmtBytes(usage.quotaBytes)} used  |  ${usage.fileCount} files"
                }
            } catch (e: Exception) {
                host.runOnUi { usageText.text = "Storage: could not load (${e.message})" }
            }
        }
    }

    override fun onTick() {
        stack.lastOrNull()?.onTick?.invoke()
    }
}
