package cloud.personal.sync

import android.content.Context
import android.app.Activity
import android.content.res.ColorStateList
import android.graphics.drawable.ColorDrawable
import android.os.Build
import android.view.WindowInsetsController
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

    /**
     * The one button of the app: a bordered box (filled for the main action) that flips its colours
     * while pressed, the way the web app's buttons do. Not a system Button.
     */
    fun button(label: String, primary: Boolean = false, onClick: () -> Unit): TextView = TextView(context).apply {
        text = if (palette.retro) label.uppercase() else label
        textSize = if (palette.retro) 12f else 13f
        typeface = Typeface.create(this@Ui.typeface, Typeface.BOLD)
        gravity = Gravity.CENTER
        minHeight = dp(44)
        minimumHeight = dp(44)
        setPadding(dp(16), dp(10), dp(16), dp(10))
        isClickable = true
        isFocusable = true
        val fill = if (primary) palette.accent else palette.surface
        val edge = if (primary) palette.accent else palette.line
        background = android.graphics.drawable.StateListDrawable().apply {
            addState(intArrayOf(android.R.attr.state_pressed), box(if (primary) palette.surface else palette.ink, if (primary) palette.accent else palette.ink))
            addState(intArrayOf(android.R.attr.state_focused), box(fill, palette.ink))
            addState(intArrayOf(), box(fill, edge))
        }
        val normalText = if (primary) palette.accentInk else palette.ink
        val pressedText = if (primary) palette.accent else palette.bg
        setTextColor(
            ColorStateList(
                arrayOf(intArrayOf(android.R.attr.state_pressed), intArrayOf()),
                intArrayOf(pressedText, normalText),
            ),
        )
        setOnClickListener { onClick() }
    }

    /** A text field in the app's look: a bordered box that gets a heavier border while focused. */
    fun field(hint: String, value: String = "", type: Int = android.text.InputType.TYPE_CLASS_TEXT): android.widget.EditText =
        android.widget.EditText(context).apply {
            this.hint = hint
            setText(value)
            inputType = type
            typeface = this@Ui.typeface
            setTextColor(palette.ink)
            setHintTextColor(palette.mute)
            textSize = 15f
            setSingleLine()
            setPadding(dp(14), dp(14), dp(14), dp(14))
            fun edge(width: Int, color: Int) = GradientDrawable().apply {
                setColor(palette.surface)
                cornerRadius = dp(palette.radiusDp).toFloat()
                setStroke(dp(width), color)
            }
            background = android.graphics.drawable.StateListDrawable().apply {
                addState(intArrayOf(android.R.attr.state_focused), edge(2, palette.ink))
                addState(intArrayOf(), edge(1, palette.line))
            }
            highlightColor = (palette.accent and 0x00FFFFFF) or 0x55000000
            if (android.os.Build.VERSION.SDK_INT >= 29) {
                textCursorDrawable = GradientDrawable().apply {
                    setColor(palette.ink)
                    setSize(dp(2), 0)
                }
            }
        }

    /** The cloud-and-folder mark in the theme's ink colour, `heightDp` tall (the art is 1.66 times wider than high). */
    fun mark(heightDp: Int): android.widget.ImageView = android.widget.ImageView(context).apply {
        setImageResource(R.drawable.ic_choud_mark)
        imageTintList = ColorStateList.valueOf(palette.ink)
        scaleType = android.widget.ImageView.ScaleType.FIT_CENTER
        contentDescription = "Choud"
        layoutParams = LinearLayout.LayoutParams((dp(heightDp) * 1.66f).toInt(), dp(heightDp))
    }

    /** The full logo (cloud, folder and the pixel "Choud" wordmark) in the theme's ink colour. */
    fun logoFull(widthDp: Int): android.widget.ImageView = android.widget.ImageView(context).apply {
        setImageResource(R.drawable.choud_logo_full)
        imageTintList = ColorStateList.valueOf(palette.ink)
        scaleType = android.widget.ImageView.ScaleType.FIT_CENTER
        contentDescription = "Choud"
        layoutParams = LinearLayout.LayoutParams(dp(widthDp), (dp(widthDp) * 647f / 720f).toInt())
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

/**
 * Paints the window and system bars in the theme's colours, with dark or light icons so the
 * clock and battery stay readable on any background.
 */
fun applyWindowTheme(activity: Activity, palette: Palette, barColor: Int = palette.bg) {
    val window = activity.window
    window.decorView // creates the window's decor view; insetsController is null before that
    window.setBackgroundDrawable(ColorDrawable(palette.bg))
    window.statusBarColor = barColor
    window.navigationBarColor = palette.bg
    val lightBars = !palette.darkSystemBars
    if (Build.VERSION.SDK_INT >= 30) {
        val mask = WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS or WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS
        try {
            window.insetsController?.setSystemBarsAppearance(if (lightBars) mask else 0, mask)
        } catch (_: Exception) {
            // cosmetic only: never let status-bar styling crash the app
        }
    } else {
        @Suppress("DEPRECATION")
        var flags = window.decorView.systemUiVisibility
        flags = if (lightBars) flags or android.view.View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR
        else flags and android.view.View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR.inv()
        @Suppress("DEPRECATION")
        window.decorView.systemUiVisibility = flags
    }
}
