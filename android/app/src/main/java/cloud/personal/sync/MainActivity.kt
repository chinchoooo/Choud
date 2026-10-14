package cloud.personal.sync

import android.Manifest
import android.app.Activity
import android.content.pm.PackageManager
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings as AndroidSettings
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import kotlin.concurrent.thread

/** Deliberately plain: login, a few switches, and a status readout. */
class MainActivity : Activity() {
    private lateinit var settings: Settings
    private val ui = Handler(Looper.getMainLooper())
    private val refreshStatus = object : Runnable {
        override fun run() {
            render()
            ui.postDelayed(this, 3000)
        }
    }
    private lateinit var root: LinearLayout

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        settings = Settings(this)
        if (settings.deviceName.isEmpty()) settings.deviceName = Build.MODEL ?: "Phone"
        root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            val pad = (16 * resources.displayMetrics.density).toInt()
            setPadding(pad, pad, pad, pad)
        }
        setContentView(ScrollView(this).apply { addView(root) })
    }

    override fun onResume() {
        super.onResume()
        ui.post(refreshStatus)
    }

    override fun onPause() {
        super.onPause()
        ui.removeCallbacks(refreshStatus)
    }

    private fun label(text: String) = TextView(this).apply { this.text = text; textSize = 16f }

    private fun render() {
        // Don't rebuild the form while the user types into it.
        if (!settings.loggedIn) {
            if (root.childCount == 0 || root.tag != "login") renderLogin()
        } else {
            renderStatus()
        }
    }

    private fun renderLogin() {
        root.tag = "login"
        root.removeAllViews()
        val url = EditText(this).apply {
            hint = "Server URL, e.g. http://100.x.y.z:8000"
            setText(settings.serverUrl)
            inputType = InputType.TYPE_TEXT_VARIATION_URI
        }
        val email = EditText(this).apply {
            hint = "Email"
            inputType = InputType.TYPE_TEXT_VARIATION_EMAIL_ADDRESS
        }
        val password = EditText(this).apply {
            hint = "Password"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        }
        val device = EditText(this).apply {
            hint = "This phone's name"
            setText(settings.deviceName)
        }
        val message = label("")
        val button = Button(this).apply {
            text = "Log in"
            setOnClickListener {
                isEnabled = false
                message.text = "Logging in…"
                val serverUrl = url.text.toString().trim()
                thread {
                    val error = try {
                        settings.serverUrl = serverUrl
                        settings.deviceName = safeDeviceName(device.text.toString())
                        ApiClient(serverUrl, settings).login(email.text.toString().trim(), password.text.toString())
                        null
                    } catch (e: Exception) {
                        e.message ?: e.javaClass.simpleName
                    }
                    runOnUiThread {
                        isEnabled = true
                        if (error == null) {
                            root.tag = null
                            requestPermissions()
                            SyncWorker.schedule(this@MainActivity, settings)
                            render()
                        } else {
                            message.text = "Login failed: $error"
                        }
                    }
                }
            }
        }
        listOf(label("Personal Cloud"), url, email, password, device, button, message).forEach { root.addView(it) }
    }

    private fun renderStatus() {
        val db = BackupDb(this)
        val done = db.count("done")
        val failed = db.count("failed")
        val uploading = db.count("uploading")
        db.close()
        root.tag = "status"
        root.removeAllViews()

        val wifi = CheckBox(this).apply {
            text = "Wi-Fi only"
            isChecked = settings.wifiOnly
            setOnCheckedChangeListener { _, on ->
                settings.wifiOnly = on
                SyncWorker.schedule(this@MainActivity, settings)
            }
        }
        val charging = CheckBox(this).apply {
            text = "Only while charging"
            isChecked = settings.chargingOnly
            setOnCheckedChangeListener { _, on ->
                settings.chargingOnly = on
                SyncWorker.schedule(this@MainActivity, settings)
            }
        }
        val syncNow = Button(this).apply {
            text = "Back up now"
            setOnClickListener {
                requestPermissions()
                SyncWorker.runNow(this@MainActivity)
            }
        }
        val battery = Button(this).apply {
            text = "Allow background running (battery)"
            setOnClickListener {
                startActivity(
                    Intent(
                        AndroidSettings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                        Uri.parse("package:$packageName"),
                    )
                )
            }
        }
        val logout = Button(this).apply {
            text = "Log out"
            setOnClickListener {
                SyncWorker.cancel(this@MainActivity)
                settings.logout()
                BackupDb(this@MainActivity).use { it.clear() }
                render()
            }
        }
        val statusLines = buildString {
            appendLine("Server: ${settings.serverUrl}")
            appendLine("Backing up to: Phone Backups/${settings.deviceName}/")
            appendLine("Backed up: $done   Failed: $failed   In progress: $uploading")
            appendLine("Last run: ${settings.lastRun}")
            if (settings.lastError.isNotEmpty()) appendLine("Problem: ${settings.lastError}")
        }
        val views = mutableListOf(label("Personal Cloud"), label(statusLines), wifi, charging, syncNow)
        val power = getSystemService(POWER_SERVICE) as PowerManager
        if (!power.isIgnoringBatteryOptimizations(packageName)) views += battery
        views += logout
        views.forEach { root.addView(it) }
    }

    private fun requestPermissions() {
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
}
