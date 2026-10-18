package cloud.personal.sync

import android.content.res.ColorStateList
import android.graphics.drawable.RippleDrawable
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import androidx.annotation.DrawableRes

/** A row of mutually exclusive choices; the chosen one is inverted (as in the web app). */
class Segmented(
    private val ui: Ui,
    private val options: List<Pair<String, String>>,
    private var selected: String,
    private val onChange: (String) -> Unit,
) {
    private val p = ui.palette
    private val cells = LinkedHashMap<String, TextView>()

    val view: LinearLayout = ui.horizontal().apply {
        background = ui.box(p.surface, p.line, radiusDp = if (p.retro) 0 else 10)
        setPadding(ui.dp(2), ui.dp(2), ui.dp(2), ui.dp(2))
        options.forEach { (id, label) ->
            val cell = ui.text(if (p.retro) label.uppercase() else label, 12.5f, bold = true).apply {
                gravity = Gravity.CENTER
                setPadding(ui.dp(14), ui.dp(8), ui.dp(14), ui.dp(8))
                setOnClickListener {
                    if (selected != id) {
                        selected = id
                        paint()
                        onChange(id)
                    }
                }
            }
            cells[id] = cell
            addView(cell, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        }
        paint()
    }

    private fun paint() {
        cells.forEach { (id, cell) ->
            val on = id == selected
            cell.setTextColor(if (on) p.bg else p.mute)
            cell.background = if (on) ui.box(p.ink, null, radiusDp = if (p.retro) 0 else 8) else null
        }
    }
}

/** A small heading that labels a group of rows. */
fun Ui.sectionTitle(value: String): TextView =
    text(if (palette.retro) value.uppercase() else value, 12f, palette.mute, bold = true).apply {
        letterSpacing = 0.04f
        setPadding(dp(16), dp(18), dp(16), dp(6))
    }

/** An empty or error state: a big quiet icon, a line of text and, optionally, a button. */
fun Ui.emptyState(@DrawableRes iconRes: Int, title: String, body: String, action: String? = null, onAction: (() -> Unit)? = null): View =
    vertical().apply {
        gravity = Gravity.CENTER
        setPadding(dp(32), dp(48), dp(32), dp(48))
        addView(icon(iconRes, 44, palette.mute))
        addView(text(title, 16f, bold = true).apply { gravity = Gravity.CENTER; setPadding(0, dp(14), 0, dp(4)) })
        addView(muted(body, 13f).apply { gravity = Gravity.CENTER })
        if (action != null && onAction != null) addView(button(action, primary = true) { onAction() }, matchWidth(18))
    }

/** Grey placeholder bars that pulse while a list loads, so the screen never looks empty or frozen. */
class Skeleton(private val ui: Ui, rows: Int = 8) {
    private val bars = ArrayList<View>()
    private var animating = false

    val view: LinearLayout = ui.vertical().apply {
        repeat(rows) {
            addView(
                ui.horizontal().apply {
                    setPadding(ui.dp(16), ui.dp(10), ui.dp(16), ui.dp(10))
                    val thumb = View(ui.context).apply { background = ui.box(ui.palette.line, null, radiusDp = if (ui.palette.retro) 0 else 8) }
                    val lines = ui.vertical().apply {
                        setPadding(ui.dp(14), 0, 0, 0)
                        val l1 = View(ui.context).apply { background = ui.box(ui.palette.line, null, radiusDp = 3) }
                        val l2 = View(ui.context).apply { background = ui.box(ui.palette.line, null, radiusDp = 3) }
                        addView(l1, LinearLayout.LayoutParams(ui.dp(120 + (it * 37) % 80), ui.dp(10)))
                        addView(l2, LinearLayout.LayoutParams(ui.dp(70), ui.dp(8)).apply { topMargin = ui.dp(8) })
                        bars += l1; bars += l2
                    }
                    bars += thumb
                    addView(thumb, LinearLayout.LayoutParams(ui.dp(44), ui.dp(44)))
                    addView(lines)
                },
                ui.matchWidth(),
            )
        }
    }

    fun start() {
        if (animating) return
        animating = true
        val on = android.provider.Settings.Global.getFloat(
            ui.context.contentResolver, android.provider.Settings.Global.ANIMATOR_DURATION_SCALE, 1f,
        ) > 0f
        if (!on) return
        bars.forEach { bar ->
            bar.animate().alpha(0.35f).setDuration(700).withEndAction(object : Runnable {
                override fun run() {
                    if (!animating) return
                    val next = if (bar.alpha < 0.6f) 1f else 0.35f
                    bar.animate().alpha(next).setDuration(700).withEndAction(this).start()
                }
            }).start()
        }
    }

    fun stop() {
        animating = false
        bars.forEach { it.animate().cancel(); it.alpha = 1f }
    }
}

/** A full-width bar with the icon, a title and an optional line beneath, used for rows of settings. */
fun Ui.iconRow(@DrawableRes iconRes: Int, title: String, subtitle: String? = null, onClick: (() -> Unit)? = null): LinearLayout =
    horizontal().apply {
        setPadding(dp(16), dp(12), dp(16), dp(12))
        addView(icon(iconRes, 22, palette.mute))
        addView(
            vertical().apply {
                setPadding(dp(16), 0, 0, 0)
                addView(text(title, 15f))
                if (subtitle != null) addView(muted(subtitle, 12f))
            },
            LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f),
        )
        if (onClick != null) {
            isClickable = true
            isFocusable = true
            background = RippleDrawable(ColorStateList.valueOf(palette.line), null, null)
            setOnClickListener { onClick() }
        }
    }

/** A thin horizontal rule that stops short of the left edge, like a list separator. */
fun Ui.inset(): View = View(context).apply {
    setBackgroundColor(palette.line)
    layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(1)).apply { leftMargin = dp(16) }
}

fun FrameLayout.addFill(child: View) =
    addView(child, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
