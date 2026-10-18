package cloud.personal.sync

import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/**
 * Chooses which address to use: the private one (a Tailscale or home address) if it answers, otherwise
 * the optional public one. Both are asked at the same moment, so a dead private address costs nothing
 * extra when the public one is fine. The private one wins unless it is more than a moment slower.
 * Blocking: call it from a background thread.
 */
object ServerPicker {
    private const val FRESH_MS = 45_000L
    private const val PRIVATE_GRACE_MS = 150L
    private var checkedAt = 0L

    private val probe: OkHttpClient = Net.client.newBuilder()
        .connectTimeout(2500, TimeUnit.MILLISECONDS)
        .readTimeout(3500, TimeUnit.MILLISECONDS)
        .callTimeout(5, TimeUnit.SECONDS)
        .build()

    private const val UNKNOWN = 0
    private const val UP = 1
    private const val DOWN = 2

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
        val chosen = choose(primary, alt)
        EventLog.log("server: using ${if (chosen == alt && alt.isNotEmpty()) "the public address" else "the private address"} ($chosen)")
        settings.activeUrl = chosen
        checkedAt = now
        return chosen
    }

    private fun choose(primary: String, alt: String): String {
        if (alt.isEmpty() || alt == primary) return primary
        if (primary.isEmpty()) return alt
        val primaryState = AtomicInteger(UNKNOWN)
        val altState = AtomicInteger(UNKNOWN)
        Thread { primaryState.set(if (answers(primary)) UP else DOWN) }.start()
        Thread { altState.set(if (answers(alt)) UP else DOWN) }.start()
        var altUpAt = 0L
        val started = System.currentTimeMillis()
        while (System.currentTimeMillis() - started < 6_000) {
            when (primaryState.get()) {
                UP -> return primary
                DOWN -> return if (altState.get() == UP || altState.get() == UNKNOWN && waitFor(altState)) alt else primary
            }
            if (altState.get() == UP) {
                if (altUpAt == 0L) altUpAt = System.currentTimeMillis()
                if (System.currentTimeMillis() - altUpAt > PRIVATE_GRACE_MS) return alt
            }
            Thread.sleep(15)
        }
        return primary
    }

    private fun waitFor(state: AtomicInteger): Boolean {
        val started = System.currentTimeMillis()
        while (state.get() == UNKNOWN && System.currentTimeMillis() - started < 6_000) Thread.sleep(15)
        return state.get() == UP
    }

    fun usingPublic(settings: Settings): Boolean =
        settings.altServerUrl.isNotBlank() && settings.activeUrl.trimEnd('/') == settings.altServerUrl.trim().trimEnd('/')
}
