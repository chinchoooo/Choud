package cloud.personal.sync

import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit

/**
 * Chooses which address to use: the private one (a Tailscale or home address) if it answers, otherwise
 * the optional public one. That way the phone works at home on the fast private path and from anywhere
 * else over the public one, with nothing to switch by hand. Blocking: call it from a background thread.
 */
object ServerPicker {
    private const val FRESH_MS = 45_000L
    private var checkedAt = 0L

    private val probe = OkHttpClient.Builder()
        .connectTimeout(2500, TimeUnit.MILLISECONDS)
        .readTimeout(3500, TimeUnit.MILLISECONDS)
        .callTimeout(5, TimeUnit.SECONDS)
        .build()

    private fun answers(base: String): Boolean = try {
        probe.newCall(Request.Builder().url(base.trimEnd('/') + "/api/health").build()).execute().use { it.code < 500 }
    } catch (e: Exception) {
        false
    }

    /** Returns the address to use (and remembers it in `settings.activeUrl`). */
    @Synchronized
    fun pick(settings: Settings, force: Boolean = false): String {
        val now = System.currentTimeMillis()
        if (!force && settings.activeUrl.isNotEmpty() && now - checkedAt < FRESH_MS) return settings.activeUrl
        val primary = settings.serverUrl.trimEnd('/')
        val alt = settings.altServerUrl.trim().trimEnd('/')
        val chosen = when {
            primary.isNotEmpty() && answers(primary) -> primary
            alt.isNotEmpty() && answers(alt) -> alt
            else -> primary // nothing answered: keep the private address, the caller reports the failure
        }
        EventLog.log("server: using ${if (chosen == alt && alt.isNotEmpty()) "the public address" else "the private address"} ($chosen)")
        settings.activeUrl = chosen
        checkedAt = now
        return chosen
    }

    fun usingPublic(settings: Settings): Boolean =
        settings.altServerUrl.isNotBlank() && settings.activeUrl.trimEnd('/') == settings.altServerUrl.trim().trimEnd('/')
}
