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
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.work.WorkInfo
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
            val url = settings.serverUrl
            val existing = apiCache
            if (existing != null && apiUrl == url) return existing
            return ApiClient(url, settings, log = EventLog::log).also {
                apiCache = it
                apiUrl = url
            }
        }

    private lateinit var content: FrameLayout
    private lateinit var tabBar: LinearLayout
    private val tabs = ArrayList<Pair<String, Tab>>()
    private val tabLabels = ArrayList<TextView>()
    private val tabIndicators = ArrayList<View>()
    private var selected = 0
    private var refreshingFacts = false
    private var datesRunRequested = false
    private var lastFactsAt = 0L

    private val tick = object : Runnable {
        override fun run() {
            if (settings.loggedIn) {
                refreshFactsIfDue()
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
        settings = Settings(this)
        if (settings.deviceName.isEmpty()) settings.deviceName = safeDeviceName(Build.MODEL ?: "Phone")
        val palette = Themes.palette(AppTheme.fromId(settings.theme))
        ui = Ui(this, palette)
        applySystemBars(palette)
        if (settings.loggedIn) showMain() else showLogin()
    }

    private fun applySystemBars(palette: Palette) = applyWindowTheme(this, palette)

    // ---------------------------------------------------------------- login

    private fun showLogin() {
        val p = ui.palette
        val column = ui.vertical().apply { setPadding(ui.dp(20), ui.dp(40), ui.dp(20), ui.dp(24)) }

        fun field(hint: String, value: String = "", type: Int = InputType.TYPE_CLASS_TEXT) = EditText(this).apply {
            this.hint = hint
            setText(value)
            inputType = type
            typeface = ui.typeface
            setTextColor(p.ink)
            setHintTextColor(p.mute)
            textSize = 15f
            setPadding(ui.dp(12), ui.dp(12), ui.dp(12), ui.dp(12))
            background = ui.box(p.surface, p.line)
        }

        val url = field("Server URL, e.g. http://100.x.y.z", settings.serverUrl, InputType.TYPE_TEXT_VARIATION_URI)
        val email = field("Email", type = InputType.TYPE_TEXT_VARIATION_EMAIL_ADDRESS)
        val password = field("Password", type = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD)
        val otp = field("Two-factor code (if turned on)", type = InputType.TYPE_CLASS_NUMBER)
        val device = field("This phone's name", settings.deviceName)
        val message = ui.text("", 13f, p.danger)

        column.addView(
            android.widget.ImageView(this).apply {
                setImageResource(if (p.darkSystemBars) R.drawable.choud_logo_dark else R.drawable.choud_logo_light)
                contentDescription = "Choud"
                adjustViewBounds = true
            },
            android.widget.LinearLayout.LayoutParams(ui.dp(120), ui.dp(120)),
        )
        column.addView(ui.heading("Choud"), ui.matchWidth(6))
        column.addView(ui.muted("Back up your photos to your own server.", 13f), ui.matchWidth(2))
        column.addView(url, ui.matchWidth(24))
        column.addView(email, ui.matchWidth(10))
        column.addView(password, ui.matchWidth(10))
        column.addView(otp, ui.matchWidth(10))
        column.addView(device, ui.matchWidth(10))
        lateinit var loginButton: android.widget.Button
        loginButton = ui.button("Log in", primary = true) {
            loginButton.isEnabled = false
            message.setTextColor(p.mute)
            message.text = "Logging in..."
            val serverUrl = url.text.toString().trim()
            thread {
                val error = try {
                    settings.serverUrl = serverUrl
                    settings.deviceName = safeDeviceName(device.text.toString())
                    EventLog.log("login: $serverUrl as ${email.text.toString().trim()}, device '${settings.deviceName}'")
                    ApiClient(serverUrl, settings, log = EventLog::log)
                        .login(email.text.toString().trim(), password.text.toString(), otp.text.toString().trim())
                    null
                } catch (e: Exception) {
                    EventLog.log("login failed: ${e.javaClass.simpleName}: ${e.message}")
                    if (e.message?.contains("two_factor_required") == true) {
                        "this account uses two-factor login: type the code from your authenticator app"
                    } else {
                        e.message ?: e.javaClass.simpleName
                    }
                }
                runOnUiThread {
                    loginButton.isEnabled = true
                    if (error == null) {
                        requestMediaPermissions()
                        SyncWorker.schedule(this, settings)
                        showMain()
                    } else {
                        message.setTextColor(p.danger)
                        message.text = "Login failed: $error"
                    }
                }
            }
        }
        column.addView(loginButton, ui.matchWidth(18))
        column.addView(message, ui.matchWidth(10))
        setContentView(ScrollView(this).apply {
            setBackgroundColor(p.bg)
            addView(column)
        })
    }

    // ---------------------------------------------------------------- main

    private fun showMain() {
        val p = ui.palette
        tabs.clear()
        tabLabels.clear()
        tabIndicators.clear()
        tabs += "Backup" to BackupTab(this)
        tabs += "Files" to FilesTab(this)
        tabs += "Photos" to PhotosTab(this)
        tabs += "More" to MoreTab(this) { logout() }

        tabBar = ui.horizontal().apply { setBackgroundColor(p.surface) }
        tabs.forEachIndexed { index, (label, _) ->
            val text = ui.text(if (p.retro) label.uppercase() else label, 14f, p.mute, bold = true).apply {
                gravity = android.view.Gravity.CENTER
                setPadding(0, ui.dp(14), 0, ui.dp(11))
            }
            val indicator = View(this).apply { setBackgroundColor(p.accent) }
            val column = ui.vertical().apply {
                addView(text, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
                addView(indicator, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ui.dp(3)))
                setOnClickListener { select(index) }
            }
            tabLabels += text
            tabIndicators += indicator
            tabBar.addView(column, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        }
        content = FrameLayout(this)
        val root = ui.vertical().apply {
            setBackgroundColor(p.bg)
            addView(tabBar, ui.matchWidth())
            addView(ui.divider())
            addView(content, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        }
        setContentView(root)
        select(selected.coerceIn(0, tabs.lastIndex))
        lastFactsAt = 0
    }

    private fun select(index: Int) {
        selected = index
        val p = ui.palette
        tabLabels.forEachIndexed { i, label ->
            val active = i == index
            label.setTextColor(if (active) p.ink else p.mute)
            tabIndicators[i].visibility = if (active) View.VISIBLE else View.INVISIBLE
        }
        content.removeAllViews()
        val tab = tabs[index].second
        content.addView(tab.view, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        tab.onShow()
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
