package cloud.personal.sync

import android.graphics.Color

/** The four looks: light, dark, and two retro ones (monospace, black and white, square). */
enum class AppTheme(val id: String, val label: String) {
    LIGHT("light", "Light"),
    DARK("dark", "Dark"),
    RETRO("retro", "Retro (black)"),
    RETRO_PAPER("retro-paper", "Retro (paper)");

    companion object {
        fun fromId(id: String?): AppTheme = entries.firstOrNull { it.id == id } ?: LIGHT
    }
}

class Palette(
    val bg: Int,
    val surface: Int,
    val ink: Int,
    val mute: Int,
    val line: Int,
    val accent: Int,
    val accentInk: Int,
    val danger: Int,
    val ok: Int,
    /** Retro themes use a coding font and square corners. */
    val retro: Boolean,
    val darkSystemBars: Boolean,
) {
    val radiusDp: Int get() = if (retro) 0 else 10
}

object Themes {
    fun palette(theme: AppTheme): Palette = when (theme) {
        AppTheme.LIGHT -> Palette(
            bg = Color.parseColor("#F9FAFB"), surface = Color.WHITE, ink = Color.parseColor("#111827"),
            mute = Color.parseColor("#6B7280"), line = Color.parseColor("#E5E7EB"),
            accent = Color.parseColor("#2563EB"), accentInk = Color.WHITE,
            danger = Color.parseColor("#DC2626"), ok = Color.parseColor("#16A34A"),
            retro = false, darkSystemBars = false,
        )
        AppTheme.DARK -> Palette(
            bg = Color.parseColor("#0F1219"), surface = Color.parseColor("#181C26"), ink = Color.parseColor("#F5F7FA"),
            mute = Color.parseColor("#949DAF"), line = Color.parseColor("#2A303E"),
            accent = Color.parseColor("#60A5FA"), accentInk = Color.parseColor("#0F1219"),
            danger = Color.parseColor("#F87171"), ok = Color.parseColor("#4ADE80"),
            retro = false, darkSystemBars = true,
        )
        // Retro drops colour on purpose: nothing is ever "only" colour-coded.
        AppTheme.RETRO -> Palette(
            bg = Color.BLACK, surface = Color.BLACK, ink = Color.WHITE,
            mute = Color.parseColor("#B0B0B0"), line = Color.parseColor("#585858"),
            accent = Color.WHITE, accentInk = Color.BLACK, danger = Color.WHITE, ok = Color.WHITE,
            retro = true, darkSystemBars = true,
        )
        AppTheme.RETRO_PAPER -> Palette(
            bg = Color.WHITE, surface = Color.WHITE, ink = Color.BLACK,
            mute = Color.parseColor("#5A5A5A"), line = Color.parseColor("#A0A0A0"),
            accent = Color.BLACK, accentInk = Color.WHITE, danger = Color.BLACK, ok = Color.BLACK,
            retro = true, darkSystemBars = false,
        )
    }
}
