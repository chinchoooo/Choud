package cloud.personal.sync

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView

/** A thin, themed progress bar: a track and a fill, drawn by hand so retro can be square. */
class ProgressBarView(context: Context, private val palette: Palette) : View(context) {
    var progress: Float = 0f
        set(value) {
            val clamped = value.coerceIn(0f, 1f)
            if (clamped != field) {
                field = clamped
                invalidate()
            }
        }

    /** The fill colour; defaults to the accent. */
    var fillColor: Int = palette.accent
        set(value) {
            field = value
            invalidate()
        }

    private val track = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
    private val fill = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
    private val frame = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = resources.displayMetrics.density
    }
    private val rect = RectF()

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        val h = (10 * resources.displayMetrics.density).toInt()
        setMeasuredDimension(MeasureSpec.getSize(widthMeasureSpec), h)
    }

    override fun onDraw(canvas: Canvas) {
        val radius = if (palette.retro) 0f else height / 2f
        track.color = palette.line
        frame.color = palette.line
        fill.color = fillColor
        rect.set(0f, 0f, width.toFloat(), height.toFloat())
        canvas.drawRoundRect(rect, radius, radius, track)
        if (progress > 0f) {
            val inset = if (palette.retro) 2f * resources.displayMetrics.density else 0f
            rect.set(inset, inset, inset + (width - 2 * inset) * progress, height - inset)
            canvas.drawRoundRect(rect, radius, radius, fill)
        }
        if (palette.retro) {
            rect.set(0f, 0f, width.toFloat(), height.toFloat())
            frame.color = palette.ink
            canvas.drawRect(rect, frame)
        }
    }
}

/** Always as tall as it is wide: the cells of the photo grid. */
class SquareImageView(context: Context) : ImageView(context) {
    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        super.onMeasure(widthMeasureSpec, widthMeasureSpec)
        setMeasuredDimension(measuredWidth, measuredWidth)
    }
}

/** Small factory for themed views, so the screens read like a description of the layout. */
class Ui(val context: Context, val palette: Palette) {
    val typeface: Typeface = if (palette.retro) Typeface.MONOSPACE else Typeface.DEFAULT

    fun dp(value: Int): Int = (value * context.resources.displayMetrics.density).toInt()

    fun box(fill: Int, stroke: Int? = null, radiusDp: Int = palette.radiusDp): GradientDrawable =
        GradientDrawable().apply {
            setColor(fill)
            cornerRadius = dp(radiusDp).toFloat()
            if (stroke != null) setStroke(dp(1), stroke)
        }

    fun text(
        value: String = "",
        sizeSp: Float = 14f,
        color: Int = palette.ink,
        bold: Boolean = false,
    ): TextView = TextView(context).apply {
        text = value
        textSize = if (palette.retro) sizeSp - 1f else sizeSp
        setTextColor(color)
        typeface = if (bold) Typeface.create(this@Ui.typeface, Typeface.BOLD) else this@Ui.typeface
    }

    fun muted(value: String = "", sizeSp: Float = 12f): TextView = text(value, sizeSp, palette.mute)

    fun heading(value: String): TextView = text(if (palette.retro) value.uppercase() else value, 16f, bold = true)

    fun vertical(): LinearLayout = LinearLayout(context).apply { orientation = LinearLayout.VERTICAL }

    fun horizontal(): LinearLayout = LinearLayout(context).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
    }

    fun card(): LinearLayout = vertical().apply {
        setPadding(dp(12), dp(10), dp(12), dp(10))
        background = box(palette.surface, palette.line)
    }

    fun divider(): View = View(context).apply {
        setBackgroundColor(palette.line)
        layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(1))
    }

    fun bar(): ProgressBarView = ProgressBarView(context, palette)

    fun button(label: String, primary: Boolean = false, onClick: () -> Unit): Button = Button(context).apply {
        text = if (palette.retro) label.uppercase() else label
        isAllCaps = false
        textSize = if (palette.retro) 12f else 13f
        typeface = this@Ui.typeface
        setTextColor(if (primary) palette.accentInk else palette.ink)
        minHeight = 0
        minimumHeight = 0
        setPadding(dp(14), dp(8), dp(14), dp(8))
        val base = box(if (primary) palette.accent else palette.surface, if (primary) palette.accent else palette.line)
        background = RippleDrawable(ColorStateList.valueOf(palette.line), base, null)
        stateListAnimator = null
        setOnClickListener { onClick() }
    }

    /** A boxed label such as "PDF" or "DIR" for items without a thumbnail. */
    fun badge(label: String, sizeDp: Int): TextView = text(label, 10f, palette.mute, bold = true).apply {
        gravity = Gravity.CENTER
        background = box(palette.bg, palette.line, radiusDp = if (palette.retro) 0 else 6)
        layoutParams = LinearLayout.LayoutParams(dp(sizeDp), dp(sizeDp))
    }

    fun spacer(heightDp: Int): View = View(context).apply {
        layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(heightDp))
    }

    fun matchWidth(topDp: Int = 0): LinearLayout.LayoutParams =
        LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
            topMargin = dp(topDp)
        }
}
