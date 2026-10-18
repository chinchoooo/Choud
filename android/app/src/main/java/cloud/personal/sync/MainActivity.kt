package cloud.personal.sync

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.BatteryManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.text.InputType
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.work.WorkInfo
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import androidx.work.WorkManager
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import kotlin.concurrent.thread

/** Holds the four tabs (Backup queue, Files, Photos, More) or the login screen. */
class MainActivity : Activity(), Host {
    private val handler = Handler(Looper.getMainLooper())

    override lateinit var settings: Settings
    override lateinit var ui: Ui

    @Volatile
    override var facts: Facts = Facts()

    private var apiCache: ApiClient? = null
    private var apiUrl: String = ""

    override val api: ApiClient
        @Synchronized get() {
            val url = settings.baseUrl
            val existing = apiCache
            if (existing != null && apiUrl == url) return existing
            return ApiClient(url, settings, log = EventLog::log).also {
                apiCache = it
                apiUrl = url
            }
        }

    private lateinit var content: FrameLayout
    private var toaster: Toaster? = null
    private lateinit var tabBar: LinearLayout
    private val tabs = ArrayList<Pair<String, Tab>>()
    private val tabLabels = ArrayList<TextView>()
    private val tabIndicators = ArrayList<View>()
    private val tabGlyphs = ArrayList<ImageView>()
    private var appStatus: TextView? = null
    private var selected = 0
    private var refreshingFacts = false
    private var datesRunRequested = false
    private var lastFactsAt = 0L

    private val tick = object : Runnable {
        override fun run() {
            if (settings.loggedIn) {
                refreshFactsIfDue()
                updateAppStatus()
                tabs.getOrNull(selected)?.second?.onTick()
                // After an update, fix the dates of everything already backed up, once per launch.
                if (!datesRunRequested && facts.datesPending > 0 && !LiveStatus.running) {
                    datesRunRequested = true
                    EventLog.log("auto: ${facts.datesPending} file(s) need their dates; starting a run")
                    SyncWorker.runNow(this@MainActivity)
                }
            }
            handler.postDelayed(this, 500)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        EventLog.init(this)
        ThumbLoader.init(this)
        settings = Settings(this)
        if (settings.deviceName.isEmpty()) settings.deviceName = safeDeviceName(Build.MODEL ?: "Phone")
        val palette = Themes.palette(AppTheme.fromId(settings.theme))
        ui = Ui(this, palette)
        applySystemBars(palette)
        if (settings.loggedIn) showBoot() else showLogin()
    }

    /** Adds a missing http://, drops a trailing slash, and rejects things that cannot be an address. */
    private fun cleanAddress(raw: String): String? {
        var text = raw.trim().trimEnd('/')
        if (text.isEmpty()) return null
        if (!text.contains("://")) text = "http://$text"
        val parsed = text.toHttpUrlOrNull() ?: return null
        return parsed.toString().trimEnd('/')
    }

    private fun applySystemBars(palette: Palette) = applyWindowTheme(this, palette)

    // ---------------------------------------------------------------- login

    private fun showLogin(notice: String? = null) {
        val p = ui.palette
        val column = ui.vertical().apply {
            gravity = android.view.Gravity.CENTER_HORIZONTAL
            setPadding(ui.dp(24), ui.dp(48), ui.dp(24), ui.dp(32))
        }

        fun field(hint: String, value: String = "", type: Int = InputType.TYPE_CLASS_TEXT) = EditText(this).apply {
            this.hint = hint
            setText(value)
            inputType = type
            typeface = ui.typeface
            setTextColor(p.ink)
            setHintTextColor(p.mute)
            textSize = 15f
            setSingleLine()
            setPadding(ui.dp(14), ui.dp(14), ui.dp(14), ui.dp(14))
            background = ui.box(p.surface, p.line)
        }

        val url = field("Server address, e.g. http://100.x.y.z", settings.serverUrl, InputType.TYPE_TEXT_VARIATION_URI)
        val email = field("Email", type = InputType.TYPE_TEXT_VARIATION_EMAIL_ADDRESS)
        val password = field("Password", type = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD)
        val otp = field("Two-factor code", type = InputType.TYPE_CLASS_NUMBER).apply { visibility = View.GONE }
        val device = field("Name of this phone", settings.deviceName)
        device.visibility = View.GONE
        val alt = field("Public address (optional, for when you are away)", settings.altServerUrl, InputType.TYPE_TEXT_VARIATION_URI)
        alt.visibility = View.GONE
        val message = ui.text(notice ?: "", 13f, p.danger).apply { gravity = android.view.Gravity.CENTER }

        column.addView(
            android.widget.ImageView(this).apply {
                setImageResource(R.drawable.ic_choud_mark)
                contentDescription = "Choud"
            },
            LinearLayout.LayoutParams(ui.dp(84), ui.dp(84)),
        )
        column.addView(ui.text(if (p.retro) "CHOUD" else "Choud", 26f, bold = true).apply { gravity = android.view.Gravity.CENTER }, ui.matchWidth(14))
        column.addView(ui.muted("Your files and photos, on your own server.", 13f).apply { gravity = android.view.Gravity.CENTER }, ui.matchWidth(4))
        column.addView(url, ui.matchWidth(32))
        column.addView(email, ui.matchWidth(10))
        column.addView(password, ui.matchWidth(10))
        column.addView(otp, ui.matchWidth(10))
        column.addView(alt, ui.matchWidth(10))
        column.addView(device, ui.matchWidth(10))
        val more = ui.text("More options", 12f, p.mute).apply {
            setPadding(0, ui.dp(12), 0, ui.dp(4))
            setOnClickListener {
                visibility = View.GONE
                device.visibility = View.VISIBLE
                alt.visibility = View.VISIBLE
            }
        }
        column.addView(more, ui.matchWidth(0))
        lateinit var loginButton: android.widget.Button
        loginButton = ui.button("Log in", primary = true) {
            loginButton.isEnabled = false
            loginButton.alpha = 0.6f
            message.setTextColor(p.mute)
            message.text = "Signing in..."
            val serverUrl = cleanAddress(url.text.toString())
            if (serverUrl == null) {
                loginButton.isEnabled = true
                loginButton.alpha = 1f
                message.setTextColor(p.danger)
                message.text = "That does not look like an address. Try something like http://100.64.0.5 or https://files.example.com"
                return@button
            }
            thread {
                var needsCode = false
                val error = try {
                    settings.serverUrl = serverUrl
                    settings.altServerUrl = cleanAddress(alt.text.toString()).orEmpty()
                    settings.activeUrl = ""
                    settings.deviceName = safeDeviceName(device.text.toString())
                    EventLog.log("login: $serverUrl as ${email.text.toString().trim()}, device '${settings.deviceName}'")
                    ApiClient(ServerPicker.pick(settings, force = true), settings, log = EventLog::log)
                        .login(email.text.toString().trim(), password.text.toString(), otp.text.toString().trim())
                    null
                } catch (e: Exception) {
                    EventLog.log("login failed: ${e.javaClass.simpleName}: ${e.message}")
                    if (e.message?.contains("two_factor_required") == true) {
                        needsCode = true
                        "This account uses two-factor login. Type the code from your authenticator app."
                    } else {
                        e.message ?: e.javaClass.simpleName
                    }
                }
                runOnUiThread {
                    loginButton.isEnabled = true
                    loginButton.alpha = 1f
                    if (error == null) {
                        requestMediaPermissions()
                        SyncWorker.schedule(this, settings)
                        showMain()
                    } else {
                        if (needsCode) otp.visibility = View.VISIBLE
                        message.setTextColor(if (needsCode) p.mute else p.danger)
                        message.text = if (needsCode) error else "Could not sign in: $error"
                    }
                }
            }
        }
        column.addView(loginButton, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ui.dp(50)).apply { topMargin = ui.dp(18) })
        column.addView(message, ui.matchWidth(14))
        setContentView(ScrollView(this).apply {
            setBackgroundColor(p.bg)
            isFillViewport = true
            addView(column)
        })
    }

    // ---------------------------------------------------------------- boot

    /**
     * The start-up screen. Each step is a real check (is the server answering, is the saved login still
     * valid); nothing here runs on a timer. If a step fails, it says why and offers to try again or to
     * open the app anyway (the files kept on the phone still work offline).
     */
    private fun showBoot() {
        val p = ui.palette
        val labels = listOf("Reaching your server", "Checking your login")
        val marks = ArrayList<ImageView>()
        val details = ArrayList<TextView>()
        val bar = ui.bar()
        val buttons = ui.vertical()

        val column = ui.vertical().apply {
            gravity = android.view.Gravity.CENTER
            setPadding(ui.dp(32), ui.dp(24), ui.dp(32), ui.dp(24))
            addView(
                ImageView(this@MainActivity).apply { setImageResource(R.drawable.ic_choud_mark) },
                LinearLayout.LayoutParams(ui.dp(96), ui.dp(96)),
            )
            addView(ui.text(if (p.retro) "CHOUD" else "Choud", 24f, bold = true).apply { gravity = android.view.Gravity.CENTER }, ui.matchWidth(14))
            val steps = ui.vertical().apply {
                labels.forEachIndexed { i, label ->
                    val mark = ui.icon(R.drawable.ic_refresh, 18, p.mute)
                    val detail = ui.muted("", 12f)
                    marks += mark
                    details += detail
                    addView(
                        ui.horizontal().apply {
                            gravity = android.view.Gravity.TOP
                            addView(mark, LinearLayout.LayoutParams(ui.dp(18), ui.dp(18)).apply { topMargin = ui.dp(2) })
                            addView(
                                ui.vertical().apply {
                                    setPadding(ui.dp(12), 0, 0, 0)
                                    addView(ui.text(label, 14f))
                                    addView(detail)
                                },
                            )
                        },
                        ui.matchWidth(if (i == 0) 0 else 10),
                    )
                }
            }
            addView(steps, LinearLayout.LayoutParams(ui.dp(260), ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = ui.dp(28) })
            addView(bar, LinearLayout.LayoutParams(ui.dp(260), ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = ui.dp(22) })
            addView(buttons, LinearLayout.LayoutParams(ui.dp(260), ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = ui.dp(22) })
        }
        setContentView(FrameLayout(this).apply { setBackgroundColor(p.bg); addView(column, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)) })

        fun mark(i: Int, state: String, detail: String = "") = runOnUiThread {
            val view = marks[i]
            view.animate().cancel()
            view.rotation = 0f
            view.setImageResource(when (state) { "done" -> R.drawable.ic_check; "failed" -> R.drawable.ic_warning; else -> R.drawable.ic_refresh })
            view.imageTintList = android.content.res.ColorStateList.valueOf(if (state == "pending") p.line else if (state == "failed") p.danger else p.ink)
            if (state == "active" && android.provider.Settings.Global.getFloat(contentResolver, android.provider.Settings.Global.ANIMATOR_DURATION_SCALE, 1f) > 0f) {
                view.animate().rotationBy(360f).setDuration(900).withEndAction(object : Runnable {
                    override fun run() { if (marks[i].drawable != null && state == "active") view.animate().rotationBy(360f).setDuration(900).withEndAction(this).start() }
                }).start()
            }
            details[i].text = detail
            bar.progress = (0 until marks.size).count { j -> j < i || (j == i && state == "done") }.toFloat() / labels.size
        }

        fun fail(i: Int, why: String) {
            mark(i, "failed", why)
            runOnUiThread {
                buttons.removeAllViews()
                buttons.addView(ui.button("Try again", primary = true) { showBoot() }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ui.dp(48)))
                buttons.addView(ui.button("Open anyway") { showMain() }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ui.dp(48)).apply { topMargin = ui.dp(8) })
            }
        }

        labels.indices.forEach { mark(it, "pending") }
        thread {
            mark(0, "active")
            try {
                ServerPicker.pick(settings, force = true)
                api.health()
                mark(0, "done", if (ServerPicker.usingPublic(settings)) "Using the public address" else "")
            } catch (e: Exception) {
                EventLog.log("boot: server not reachable: ${e.javaClass.simpleName}: ${e.message}")
                fail(0, "No answer. Is Tailscale on, and is the server running?")
                return@thread
            }
            mark(1, "active")
            try {
                api.usage()
                mark(1, "done")
            } catch (e: AuthError) {
                EventLog.log("boot: saved login is no longer valid")
                runOnUiThread {
                    settings.logout()
                    showLogin("Your session ended. Please sign in again.")
                }
                return@thread
            } catch (e: Exception) {
                EventLog.log("boot: login check failed: ${e.javaClass.simpleName}: ${e.message}")
                fail(1, "Could not check your login: ${e.message}")
                return@thread
            }
            runOnUiThread { showMain() }
        }
    }

    // ---------------------------------------------------------------- main

    private fun showMain() {
        val p = ui.palette
        tabs.clear()
        tabLabels.clear()
        tabIndicators.clear()
        tabGlyphs.clear()
        tabs += "Backup" to BackupTab(this)
        tabs += "Files" to FilesTab(this)
        tabs += "Photos" to PhotosTab(this)
        tabs += "More" to MoreTab(this) { logout() }
        val icons = listOf(R.drawable.ic_nav_backup, R.drawable.ic_nav_files, R.drawable.ic_nav_photos, R.drawable.ic_nav_more)

        // Top bar: the mark, the name, and what the backup is doing right now.
        appStatus = ui.muted("", 12f)
        val appBar = ui.horizontal().apply {
            setBackgroundColor(p.surface)
            setPadding(ui.dp(16), ui.dp(10), ui.dp(16), ui.dp(10))
            addView(
                ImageView(this@MainActivity).apply {
                    setImageResource(R.drawable.ic_choud_mark)
                    contentDescription = "Choud"
                },
                LinearLayout.LayoutParams(ui.dp(30), ui.dp(30)),
            )
            addView(
                ui.text(if (p.retro) "CHOUD" else "Choud", 17f, bold = true).apply { setPadding(ui.dp(10), 0, 0, 0) },
                LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f),
            )
            addView(appStatus)
        }

        // Bottom navigation: an icon and a label per tab; the current one is inverted, as on the web.
        tabBar = ui.horizontal().apply { setBackgroundColor(p.surface) }
        tabs.forEachIndexed { index, (label, _) ->
            val pill = ui.vertical().apply {
                gravity = android.view.Gravity.CENTER
                setPadding(ui.dp(18), ui.dp(5), ui.dp(18), ui.dp(5))
            }
            val glyph = ui.icon(icons[index], 22, p.mute)
            pill.addView(glyph)
            val text = ui.text(if (p.retro) label.uppercase() else label, 10.5f, p.mute, bold = true).apply {
                gravity = android.view.Gravity.CENTER
                setPadding(0, ui.dp(2), 0, 0)
            }
            val column = ui.vertical().apply {
                gravity = android.view.Gravity.CENTER
                setPadding(0, ui.dp(8), 0, ui.dp(8))
                addView(pill, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT))
                addView(text)
                isClickable = true
                contentDescription = label
                setOnClickListener { select(index) }
            }
            tabLabels += text
            tabIndicators += pill
            tabGlyphs += glyph
            tabBar.addView(column, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        }
        content = FrameLayout(this)
        val root = ui.vertical().apply {
            setBackgroundColor(p.bg)
            addView(appBar, ui.matchWidth())
            addView(ui.divider())
            addView(content, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
            addView(ui.divider())
            addView(tabBar, ui.matchWidth())
        }
        val stack = FrameLayout(this).apply { addView(root) }
        toaster = Toaster(ui, stack)
        setContentView(stack)
        select(selected.coerceIn(0, tabs.lastIndex))
        lastFactsAt = 0
    }

    private fun select(index: Int) {
        selected = index
        val p = ui.palette
        tabLabels.forEachIndexed { i, label ->
            val active = i == index
            label.setTextColor(if (active) p.ink else p.mute)
            // The active tab's icon sits on a filled pill: ink background, page-coloured icon.
            tabIndicators[i].background = if (active) ui.box(p.ink, null, radiusDp = if (p.retro) 0 else 16) else null
            tabGlyphs[i].imageTintList = android.content.res.ColorStateList.valueOf(if (active) p.bg else p.mute)
        }
        content.removeAllViews()
        val tab = tabs[index].second
        content.addView(tab.view, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        tab.onShow()
    }

    /** The one-line state shown in the top bar: what the backup is doing, in plain words. */
    private fun updateAppStatus() {
        val bar = appStatus ?: return
        val text = when {
            LiveStatus.running -> "Backing up..."
            facts.failed > 0 -> "${facts.failed} failed"
            facts.pending > 0 -> "${facts.pending} waiting"
            facts.visible > 0 -> "Backed up"
            else -> ""
        }
        if (bar.text.toString() != text) bar.text = text
    }

    private fun logout() {
        SyncWorker.cancel(this)
        LiveStatus.cancelRequested = true
        settings.logout()
        BackupDb(this).use { it.clear() }
        ThumbLoader.clear()
        EventLog.log("user: logged out, backup state cleared")
        facts = Facts()
        apiCache = null
        showLogin()
    }

    override fun onResume() {
        super.onResume()
        handler.post(tick)
    }

    override fun onPause() {
        super.onPause()
        handler.removeCallbacks(tick)
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (settings.loggedIn && tabs.getOrNull(selected)?.second?.onBack() == true) return
        @Suppress("DEPRECATION")
        super.onBackPressed()
    }

    // ---------------------------------------------------------------- Host

    override fun openViewer(items: List<RemoteItem>, index: Int) {
        ViewerSession.items = items
        startActivity(Intent(this, ViewerActivity::class.java).putExtra(ViewerActivity.EXTRA_INDEX, index))
    }

    override fun onThemeChanged() {
        recreate()
    }

    override fun runOnUi(block: () -> Unit) {
        runOnUiThread(block)
    }

    override fun toast(text: String, actionLabel: String?, onAction: (() -> Unit)?) {
        runOnUiThread {
            val shown = toaster
            if (shown != null) shown.show(text, actionLabel, onAction) else android.widget.Toast.makeText(this, text, android.widget.Toast.LENGTH_SHORT).show()
        }
    }

    override fun requestMediaPermissions() {
        val wanted = if (Build.VERSION.SDK_INT >= 33) {
            arrayOf(
                Manifest.permission.READ_MEDIA_IMAGES,
                Manifest.permission.READ_MEDIA_VIDEO,
                Manifest.permission.POST_NOTIFICATIONS,
            )
        } else {
            arrayOf(Manifest.permission.READ_EXTERNAL_STORAGE)
        }
        val missing = wanted.filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
        if (missing.isNotEmpty()) requestPermissions(missing.toTypedArray(), 1)
    }

    // ---------------------------------------------------------------- facts

    private fun refreshFactsIfDue() {
        val now = System.currentTimeMillis()
        if (refreshingFacts || now - lastFactsAt < 3000) return
        refreshingFacts = true
        lastFactsAt = now
        thread {
            try {
                facts = collectFacts()
            } catch (e: Exception) {
                facts = facts.copy(lastError = "Could not read status: ${e.javaClass.simpleName}: ${e.message}")
            } finally {
                refreshingFacts = false
            }
        }
    }

    private fun collectFacts(): Facts {
        val db = BackupDb(this)
        val done = db.count("done")
        val failed = db.count("failed")
        val uploading = db.count("uploading")
        val failures = db.failures(5)
        val datesPending = db.countDatesPending()
        val visible = try {
            CameraBackup(this, settings, db, api).visibleCount()
        } catch (e: SecurityException) {
            0
        }
        db.close()

        fun perm(p: String) = if (checkSelfPermission(p) == PackageManager.PERMISSION_GRANTED) "yes" else "NO"
        val permissions = if (Build.VERSION.SDK_INT >= 33) {
            "photos ${perm(Manifest.permission.READ_MEDIA_IMAGES)}, videos ${perm(Manifest.permission.READ_MEDIA_VIDEO)}, " +
                "notifications ${perm(Manifest.permission.POST_NOTIFICATIONS)}"
        } else {
            "storage ${perm(Manifest.permission.READ_EXTERNAL_STORAGE)}"
        }
        val power = getSystemService(POWER_SERVICE) as PowerManager
        return Facts(
            visible = visible,
            done = done,
            failed = failed,
            uploading = uploading,
            failures = failures,
            datesPending = datesPending,
            network = networkText(),
            power = powerText(),
            permissions = permissions,
            batteryExempt = power.isIgnoringBatteryOptimizations(packageName),
            jobNow = workText(SyncWorker.ONCE),
            jobHourly = workText(SyncWorker.PERIODIC),
            lastRun = settings.lastRun,
            lastError = settings.lastError,
        )
    }

    private fun networkText(): String {
        val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val network = cm.activeNetwork ?: return "OFFLINE"
        val caps = cm.getNetworkCapabilities(network) ?: return "unknown"
        val kinds = buildList {
            if (caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)) add("Wi-Fi")
            if (caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR)) add("mobile data")
            if (caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)) add("ethernet")
            if (caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN)) add("VPN (Tailscale?)")
        }.joinToString(" + ").ifEmpty { "other" }
        val metered = if (caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED)) "unmetered" else "metered"
        val internet = if (caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)) "internet ok" else "no internet check"
        return "$kinds, $metered, $internet"
    }

    private fun powerText(): String {
        val intent = registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED)) ?: return "unknown"
        val level = intent.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
        val scale = intent.getIntExtra(BatteryManager.EXTRA_SCALE, 100)
        val plugged = intent.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) != 0
        return "${level * 100 / scale}% ${if (plugged) "charging" else "on battery"}"
    }

    private fun workText(name: String): String {
        val infos = try {
            WorkManager.getInstance(this).getWorkInfosForUniqueWork(name).get()
        } catch (e: Exception) {
            return "unknown (${e.javaClass.simpleName})"
        }
        val info = infos.firstOrNull() ?: return "not scheduled"
        val state = when (info.state) {
            WorkInfo.State.ENQUEUED -> "waiting for its conditions / next slot"
            WorkInfo.State.RUNNING -> "RUNNING"
            WorkInfo.State.SUCCEEDED -> "finished OK"
            WorkInfo.State.FAILED -> "FAILED (see log)"
            WorkInfo.State.BLOCKED -> "blocked"
            WorkInfo.State.CANCELLED -> "cancelled"
        }
        val next = info.nextScheduleTimeMillis.takeIf { it != Long.MAX_VALUE && info.state == WorkInfo.State.ENQUEUED }
            ?.let { " (next " + DateTimeFormatter.ofPattern("HH:mm:ss").withZone(ZoneId.systemDefault()).format(Instant.ofEpochMilli(it)) + ")" }
            .orEmpty()
        return "$state, attempt ${info.runAttemptCount + 1}$next"
    }
}

/** The list the viewer is browsing; set right before it opens (a list of file entries is not Parcelable-cheap). */
object ViewerSession {
    @Volatile
    var items: List<RemoteItem> = emptyList()
}
