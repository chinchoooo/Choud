package cloud.personal.sync

import android.view.View

/** What the tabs need from the activity that hosts them. */
interface Host {
    val ui: Ui
    val settings: Settings

    /** One shared client for the screens (browsing, thumbnails, favorites). */
    val api: ApiClient

    /** The latest slow-to-compute facts (counts, network, job state), refreshed in the background. */
    val facts: Facts

    fun openViewer(items: List<RemoteItem>, index: Int)
    fun onThemeChanged()
    fun requestMediaPermissions()
    fun runOnUi(block: () -> Unit)
}

interface Tab {
    val view: View

    /** Called when the tab becomes visible. */
    fun onShow() {}

    /** Called about twice a second while the tab is visible. */
    fun onTick() {}

    /** Back pressed: return true if the tab handled it (e.g. went up a folder). */
    fun onBack(): Boolean = false
}

/** Slow-to-compute status shown on the Backup and More tabs. */
data class Facts(
    val visible: Int = 0,
    val done: Int = 0,
    val failed: Int = 0,
    val uploading: Int = 0,
    val failures: List<String> = emptyList(),
    val network: String = "checking...",
    val power: String = "",
    val permissions: String = "",
    val batteryExempt: Boolean = false,
    val jobNow: String = "",
    val jobHourly: String = "",
    val lastRun: String = "never",
    val lastError: String = "",
) {
    /** Photos the app can see that are neither backed up nor failed. */
    val pending: Int get() = (visible - done - failed).coerceAtLeast(0)
}
