package cloud.personal.sync

import android.content.res.ColorStateList
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.drawable.RippleDrawable
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import androidx.annotation.DrawableRes

/**
 * An on/off switch drawn in the app's theme. Modern themes get a pill; the retro themes get a
 * square box that reads "ON" (filled) or "OFF" (outlined), so state never depends on colour alone.
 */
class ChoudSwitch(private val ui: Ui, checked: Boolean, private val onChange: (Boolean) -> Unit) : View(ui.context) {
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val rect = RectF()
    var isOn: Boolean = checked
        set(value) {
            field = value
            invalidate()
        }

    init {
        isClickable = true
        isFocusable = true
        setOnClickListener { toggle() }
        layoutParams = LinearLayout.LayoutParams(ui.dp(52), ui.dp(30))
    }

    fun toggle() {
        isOn = !isOn
        onChange(isOn)
    }

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) = setMeasuredDimension(ui.dp(52), ui.dp(30))

    override fun onDraw(canvas: Canvas) {
        val p = ui.palette
        val w = width.toFloat()
        val h = height.toFloat()
        val stroke = ui.dp(1).toFloat().coerceAtLeast(1f)
        rect.set(stroke, stroke, w - stroke, h - stroke)
        if (p.retro) {
            paint.style = Paint.Style.FILL
            paint.color = if (isOn) p.ink else p.bg
            canvas.drawRect(rect, paint)
            paint.style = Paint.Style.STROKE
            paint.strokeWidth = stroke * 1.5f
            paint.color = p.ink
            canvas.drawRect(rect, paint)
            paint.style = Paint.Style.FILL
            paint.textAlign = Paint.Align.CENTER
            paint.typeface = android.graphics.Typeface.create(android.graphics.Typeface.MONOSPACE, android.graphics.Typeface.BOLD)
            paint.textSize = ui.dp(11).toFloat()
            paint.color = if (isOn) p.bg else p.ink
            canvas.drawText(if (isOn) "ON" else "OFF", w / 2, h / 2 + paint.textSize * 0.35f, paint)
            return
        }
        paint.style = Paint.Style.FILL
        paint.color = if (isOn) p.accent else p.line
        canvas.drawRoundRect(rect, h / 2, h / 2, paint)
        val r = h / 2 - ui.dp(4)
        val cx = if (isOn) w - h / 2 else h / 2
        paint.color = if (isOn) p.accentInk else p.surface
        canvas.drawCircle(cx, h / 2, r, paint)
    }
}

private fun Ui.rowRipple() = RippleDrawable(ColorStateList.valueOf(palette.line), null, null)

/**
 * The one row used on every settings screen: optional icon, title, optional second line, and
 * something on the right (a chevron, a value, a switch or a check). At least 56 dp tall.
 */
fun Ui.listRow(
    @DrawableRes leading: Int? = null,
    title: String,
    subtitle: String? = null,
    value: String? = null,
    trailing: View? = null,
    danger: Boolean = false,
    chevron: Boolean = true,
    onClick: (() -> Unit)? = null,
): LinearLayout {
    val ink = if (danger) palette.danger else palette.ink
    return LinearLayout(context).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        minimumHeight = dp(if (subtitle == null) 56 else 64)
        setPadding(dp(20), dp(8), dp(16), dp(8))
        if (leading != null) {
            addView(icon(leading, 22, if (danger) palette.danger else palette.mute))
            addView(View(context), LinearLayout.LayoutParams(dp(16), 1))
        }
        val texts = vertical().apply {
            addView(text(title, 15f, ink).apply { if (danger && palette.retro) setTypeface(typeface, android.graphics.Typeface.BOLD) })
            if (subtitle != null) addView(muted(subtitle, 12f).apply { setPadding(0, dp(2), 0, 0) })
        }
        addView(texts, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        if (value != null) {
            addView(muted(value, 13f).apply { setPadding(dp(12), 0, 0, 0); maxLines = 1; ellipsize = android.text.TextUtils.TruncateAt.END })
        }
        if (trailing != null) {
            (trailing.layoutParams as? LinearLayout.LayoutParams)?.leftMargin = dp(12)
            addView(trailing)
        } else if (onClick != null && chevron) {
            addView(icon(R.drawable.ic_chevron, 18, palette.mute).apply { (layoutParams as LinearLayout.LayoutParams).leftMargin = dp(10) })
        }
        if (onClick != null) {
            isClickable = true
            isFocusable = true
            background = rowRipple()
            setOnClickListener { onClick() }
        }
        contentDescription = listOfNotNull(title, subtitle, value).joinToString(", ")
    }
}

/** A row with a switch on the right. Tapping anywhere on the row flips it. */
fun Ui.switchRow(
    @DrawableRes leading: Int? = null,
    title: String,
    subtitle: String? = null,
    checked: Boolean,
    onChange: (Boolean) -> Unit,
): LinearLayout {
    val sw = ChoudSwitch(this, checked, onChange)
    return listRow(leading = leading, title = title, subtitle = subtitle, trailing = sw, chevron = false) { sw.toggle() }
}

/** A pick-one row: the chosen row shows a check (and a border mark in retro). */
fun Ui.choiceRow(title: String, subtitle: String? = null, selected: Boolean, onClick: () -> Unit): LinearLayout =
    listRow(
        title = title,
        subtitle = subtitle,
        trailing = if (selected) icon(R.drawable.ic_check, 20, palette.ink) else View(context).apply {
            layoutParams = LinearLayout.LayoutParams(dp(20), dp(20))
        },
        chevron = false,
        onClick = onClick,
    ).apply { isSelected = selected }

/** A small heading above a group of rows. */
fun Ui.sectionHeader(title: String): android.widget.TextView =
    text(if (palette.retro) title.uppercase() else title, 12f, palette.mute, bold = true).apply {
        setPadding(dp(20), dp(22), dp(20), dp(6))
    }

/** A bordered group of rows with a hairline between them. */
fun Ui.group(vararg rows: View): LinearLayout = vertical().apply {
    background = box(palette.surface, palette.line)
    rows.forEachIndexed { i, row ->
        if (i > 0) addView(divider())
        addView(row, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
    }
}

/** A header bar for a pushed screen: back arrow, title, and up to a few 48 dp actions. */
fun Ui.topBar(title: String, onBack: (() -> Unit)?, vararg actions: View): LinearLayout = horizontal().apply {
    setBackgroundColor(palette.surface)
    minimumHeight = dp(56)
    if (onBack != null) addView(iconOnly(R.drawable.ic_back, "Back", palette.ink) { onBack() })
    addView(
        text(if (palette.retro) title.uppercase() else title, 17f, bold = true).apply {
            maxLines = 1
            ellipsize = android.text.TextUtils.TruncateAt.END
            setPadding(if (onBack == null) dp(16) else dp(4), 0, dp(8), 0)
        },
        LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f),
    )
    actions.forEach { addView(it) }
}

/** An inline notice with a tinted border and an optional action. */
fun Ui.banner(message: String, actionLabel: String? = null, onAction: (() -> Unit)? = null): LinearLayout = horizontal().apply {
    setPadding(dp(14), dp(10), dp(10), dp(10))
    background = box(palette.surface, palette.ink)
    addView(icon(R.drawable.ic_info, 18, palette.ink))
    addView(text(message, 13f).apply { setPadding(dp(10), 0, dp(8), 0) }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
    if (actionLabel != null && onAction != null) {
        addView(text(if (palette.retro) actionLabel.uppercase() else actionLabel, 13f, palette.accent, bold = true).apply {
            setPadding(dp(10), dp(10), dp(10), dp(10))
            setOnClickListener { onAction() }
        })
    }
}

/** A thin themed scroll handle instead of the system's, and no stretchy overscroll glow. */
fun <T : View> T.styleScroll(ui: Ui): T {
    overScrollMode = View.OVER_SCROLL_NEVER
    isVerticalScrollBarEnabled = true
    scrollBarSize = ui.dp(3)
    if (android.os.Build.VERSION.SDK_INT >= 29) {
        verticalScrollbarThumbDrawable = android.graphics.drawable.GradientDrawable().apply {
            setColor(ui.palette.mute)
            cornerRadius = if (ui.palette.retro) 0f else ui.dp(2).toFloat()
        }
        verticalScrollbarTrackDrawable = null
    }
    return this
}
