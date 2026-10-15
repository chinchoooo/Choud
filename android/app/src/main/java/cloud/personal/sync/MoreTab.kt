package cloud.personal.sync

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings as AndroidSettings
import android.view.View
import android.widget.CheckBox
import android.widget.LinearLayout
import android.widget.RadioButton
import android.widget.RadioGroup
import android.widget.ScrollView
import android.widget.TextView
import kotlin.concurrent.thread

/** Account, storage, theme, background settings, status details and the full activity log. */
class MoreTab(private val host: Host, private val onLogout: () -> Unit) : Tab {
    private val ui = host.ui
    private val palette = ui.palette
    private val settings = host.settings

    private val usageText = ui.muted("", 12f)
    private val usageBar = ui.bar()
    private val factsView = ui.text("", 12f).apply { typeface = android.graphics.Typeface.MONOSPACE }
    private val messageView = ui.muted("", 12f)
    private val logView = ui.text("", 11f).apply {
        typeface = android.graphics.Typeface.MONOSPACE
        setTextIsSelectable(true)
    }
    private var shownLogVersion = -1
    private var usageLoadedAt = 0L

    override val view: View = ScrollView(ui.context).apply {
        setBackgroundColor(palette.bg)
        val column = ui.vertical().apply { setPadding(ui.dp(14), ui.dp(12), ui.dp(14), ui.dp(28)) }

        // Account and storage
        column.addView(section("Account"), ui.matchWidth())
        column.addView(
            ui.card().apply {
                addView(ui.text(settings.deviceName.ifEmpty { "This phone" }, 14f, bold = true))
                addView(ui.muted(settings.serverUrl, 12f), ui.matchWidth(2))
                addView(usageBar, ui.matchWidth(10))
                addView(usageText, ui.matchWidth(4))
            },
            ui.matchWidth(6),
        )

        // Theme
        column.addView(section("Theme"), ui.matchWidth(18))
        val group = RadioGroup(ui.context).apply { orientation = RadioGroup.VERTICAL }
        for (theme in AppTheme.entries) {
            group.addView(
                RadioButton(ui.context).apply {
                    id = View.generateViewId()
                    text = theme.label
                    typeface = ui.typeface
                    setTextColor(palette.ink)
                    isChecked = settings.theme == theme.id
                    setOnClickListener {
                        if (settings.theme != theme.id) {
                            settings.theme = theme.id
                            host.onThemeChanged()
                        }
                    }
                },
            )
        }
        column.addView(ui.card().apply { addView(group) }, ui.matchWidth(6))

        // Background backup settings
        column.addView(section("Background backup"), ui.matchWidth(18))
        column.addView(
            ui.card().apply {
                addView(check("Wi-Fi only", settings.wifiOnly) { on ->
                    settings.wifiOnly = on
                    EventLog.log("setting: Wi-Fi only = $on")
                    SyncWorker.schedule(host.ui.context, settings)
                })
                addView(check("Only while charging", settings.chargingOnly) { on ->
                    settings.chargingOnly = on
                    EventLog.log("setting: charging only = $on")
                    SyncWorker.schedule(host.ui.context, settings)
                })
                addView(ui.muted("Applies to the hourly automatic run. \"Back up now\" ignores these.", 11f), ui.matchWidth(4))
            },
            ui.matchWidth(6),
        )

        // Tools
        column.addView(section("Tools"), ui.matchWidth(18))
        val tools = ui.vertical().apply {
            addView(ui.button("Test connection to the server") { testConnection() }, ui.matchWidth())
            addView(
                ui.button("Allow background running (battery)") {
                    host.ui.context.startActivity(
                        Intent(
                            AndroidSettings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                            Uri.parse("package:${host.ui.context.packageName}"),
                        ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                    )
                },
                ui.matchWidth(8),
            )
            addView(ui.button("Log out") { onLogout() }, ui.matchWidth(8))
            addView(messageView, ui.matchWidth(6))
        }
        column.addView(tools, ui.matchWidth(6))

        // Status details
        column.addView(section("Status"), ui.matchWidth(18))
        column.addView(ui.card().apply { addView(factsView) }, ui.matchWidth(6))

        // Log
        column.addView(section("Activity log (every call, newest at the bottom)"), ui.matchWidth(18))
        val logButtons = ui.horizontal().apply {
            addView(ui.button("Copy log") {
                val clip = host.ui.context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                clip.setPrimaryClip(ClipData.newPlainText("Personal Cloud log", EventLog.tail(200_000)))
                messageView.text = "Log copied."
            })
            addView(View(ui.context), LinearLayout.LayoutParams(ui.dp(8), 1))
            addView(ui.button("Clear log") { EventLog.clear() })
        }
        column.addView(logButtons, ui.matchWidth(6))
        column.addView(ui.card().apply { addView(logView) }, ui.matchWidth(8))
        addView(column)
    }

    private fun section(title: String): TextView =
        ui.text(if (palette.retro) title.uppercase() else title, 13f, palette.mute, bold = true)

    private fun check(label: String, checked: Boolean, onChange: (Boolean) -> Unit) = CheckBox(ui.context).apply {
        text = label
        typeface = ui.typeface
        setTextColor(palette.ink)
        isChecked = checked
        setOnCheckedChangeListener { _, on -> onChange(on) }
    }

    private fun testConnection() {
        messageView.text = "Testing..."
        val started = System.nanoTime()
        thread {
            val result = try {
                val body = host.api.health()
                "OK in ${(System.nanoTime() - started) / 1_000_000} ms: $body"
            } catch (e: Exception) {
                "FAILED: ${e.javaClass.simpleName}: ${e.message}"
            }
            EventLog.log("connection test -> $result")
            host.runOnUi { messageView.text = "Connection test: $result" }
        }
    }

    override fun onShow() {
        loadUsage()
        onTick()
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
        val f = host.facts
        factsView.text = buildString {
            appendLine("Photos    ${f.visible} visible | ${f.done} backed up | ${f.failed} failed")
            appendLine("Network   ${f.network}")
            appendLine("Power     ${f.power}")
            appendLine("Battery   exemption ${if (f.batteryExempt) "granted" else "NOT granted"}")
            appendLine("Perms     ${f.permissions}")
            appendLine("Job now   ${f.jobNow}")
            appendLine("Job hourly ${f.jobHourly}")
            appendLine("Last run  ${f.lastRun}")
            if (f.lastError.isNotEmpty()) appendLine("PROBLEM   ${f.lastError}")
        }.trimEnd()
        if (EventLog.version != shownLogVersion) {
            shownLogVersion = EventLog.version
            logView.text = EventLog.tail(8000)
        }
    }
}
