package cloud.personal.sync

import android.graphics.Canvas
import android.graphics.Paint
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView

/**
 * A progress bar in the style of the brand sheet's loading screens: an outlined box filled with solid
 * blocks, one more for each step that really finished. While a step is running the next block blinks,
 * so it is always clear that something is happening.
 */
class BlockBar(private val ui: Ui) : View(ui.context) {
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val handler = Handler(Looper.getMainLooper())
    private var blink = true
    private val total = 18

    /** 0..1: how far the real work has got. */
    var progress: Float = 0f
        set(value) {
            field = value.coerceIn(0f, 1f)
            invalidate()
        }

    private val pulse = object : Runnable {
        override fun run() {
            blink = !blink
            invalidate()
            handler.postDelayed(this, 380)
        }
    }

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        handler.post(pulse)
    }

    override fun onDetachedFromWindow() {
        handler.removeCallbacks(pulse)
        super.onDetachedFromWindow()
    }

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        setMeasuredDimension(MeasureSpec.getSize(widthMeasureSpec), ui.dp(26))
    }

    override fun onDraw(canvas: Canvas) {
        val ink = ui.palette.ink
        val stroke = ui.dp(2).toFloat()
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = stroke
        paint.color = ink
        canvas.drawRect(stroke / 2, stroke / 2, width - stroke / 2, height - stroke / 2, paint)
        paint.style = Paint.Style.FILL
        val inner = ui.dp(5).toFloat()
        val gap = ui.dp(2).toFloat()
        val slot = (width - 2 * inner - gap * (total - 1)) / total
        val filled = (progress * total).toInt()
        for (i in 0 until total) {
            val running = i == filled && progress < 1f
            if (i >= filled && !(running && blink)) continue
            val left = inner + i * (slot + gap)
            canvas.drawRect(left, inner, left + slot, height - inner, paint)
        }
    }
}

/**
 * The full-screen loading page (the logo, a line saying what is happening, the block bar). Shown on
 * the first start after signing in, while the library is fetched for the first time, with a line
 * for each step as it really happens.
 */
class LoadingScreen(private val ui: Ui) {
    private val status: TextView = ui.text("", 14f).apply {
        gravity = Gravity.CENTER
        typeface = android.graphics.Typeface.MONOSPACE
    }
    private val bar = BlockBar(ui)
    private val buttons = ui.vertical()

    val view: View = FrameLayout(ui.context).apply {
        setBackgroundColor(ui.palette.bg)
        val column = ui.vertical().apply {
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(ui.dp(32), 0, ui.dp(32), 0)
            addView(ui.logoFull(220))
            addView(status, ui.matchWidth(34))
            addView(bar, LinearLayout.LayoutParams(ui.dp(260), ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = ui.dp(18) })
            addView(buttons, LinearLayout.LayoutParams(ui.dp(260), ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = ui.dp(22) })
        }
        addView(column, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.CENTER))
    }

    /** Says what is happening now and how far along it is. Call on the main thread. */
    fun step(text: String, progress: Float) {
        status.setTextColor(ui.palette.ink)
        status.text = text
        bar.progress = progress
        buttons.removeAllViews()
    }

    /** A step failed: say why and offer the way forward. */
    fun failed(text: String, retry: () -> Unit, openAnyway: (() -> Unit)?) {
        status.setTextColor(ui.palette.danger)
        status.text = text
        buttons.removeAllViews()
        buttons.addView(ui.button("Try again", primary = true) { retry() }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ui.dp(48)))
        if (openAnyway != null) {
            buttons.addView(ui.button("Open anyway") { openAnyway() }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ui.dp(48)).apply { topMargin = ui.dp(8) })
        }
    }
}
