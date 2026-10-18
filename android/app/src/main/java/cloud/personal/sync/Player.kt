package cloud.personal.sync

import android.graphics.Canvas
import android.graphics.Paint
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView

/**
 * A seek bar drawn in the app's own look: a thin track, the played part filled in the ink colour and
 * a square handle (round in the modern themes). Replaces the system SeekBar.
 */
class ChoudSeek(private val ui: Ui, private val onSeek: (fraction: Float) -> Unit) : View(ui.context) {
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private var dragging = false
    private var shown = 0f

    /** 0..1: how much has played. Ignored while the finger is down. */
    var fraction: Float
        get() = shown
        set(value) {
            if (!dragging) {
                shown = value.coerceIn(0f, 1f)
                invalidate()
            }
        }

    init {
        isClickable = true
        minimumHeight = ui.dp(40)
    }

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        setMeasuredDimension(MeasureSpec.getSize(widthMeasureSpec), ui.dp(40))
    }

    override fun onDraw(canvas: Canvas) {
        val p = ui.palette
        val pad = ui.dp(10).toFloat()
        val cy = height / 2f
        val left = pad
        val right = width - pad
        val x = left + (right - left) * fraction
        val track = ui.dp(3).toFloat()
        paint.style = Paint.Style.FILL
        paint.color = p.line
        canvas.drawRect(left, cy - track / 2, right, cy + track / 2, paint)
        paint.color = p.ink
        canvas.drawRect(left, cy - track / 2, x, cy + track / 2, paint)
        val half = ui.dp(if (dragging) 9 else 7).toFloat()
        if (p.retro) {
            canvas.drawRect(x - half, cy - half, x + half, cy + half, paint)
            paint.color = p.bg
            paint.style = Paint.Style.STROKE
            paint.strokeWidth = ui.dp(1).toFloat()
            canvas.drawRect(x - half, cy - half, x + half, cy + half, paint)
        } else {
            canvas.drawCircle(x, cy, half, paint)
        }
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        val pad = ui.dp(10).toFloat()
        fun at(e: MotionEvent) = ((e.x - pad) / (width - 2 * pad)).coerceIn(0f, 1f)
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                parent?.requestDisallowInterceptTouchEvent(true)
                dragging = true
                shown = at(event)
                invalidate()
            }
            MotionEvent.ACTION_MOVE -> {
                shown = at(event)
                invalidate()
            }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                shown = at(event)
                dragging = false
                invalidate()
                if (event.actionMasked == MotionEvent.ACTION_UP) onSeek(shown)
            }
        }
        return true
    }
}

/** What the player bar needs from whatever is playing (a VideoView, a MediaPlayer). */
interface PlayerSource {
    fun isPlaying(): Boolean
    fun toggle()
    fun positionMs(): Int
    fun durationMs(): Int
    fun seekToMs(ms: Int)
}

/** Play / pause, the time played, a seek bar and the length: the same controls for video and audio. */
class PlayerBar(private val ui: Ui, private val source: PlayerSource) : LinearLayout(ui.context) {
    private val play: ImageView
    private val elapsed: TextView = ui.muted("0:00", 12f)
    private val total: TextView = ui.muted("0:00", 12f)
    private val seek = ChoudSeek(ui) { fraction ->
        val duration = source.durationMs()
        if (duration > 0) source.seekToMs((duration * fraction).toInt())
    }

    init {
        orientation = HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        setPadding(ui.dp(4), 0, ui.dp(12), 0)
        play = ui.iconOnly(R.drawable.ic_play, "Play", ui.palette.ink) {
            source.toggle()
            refresh()
        }
        addView(play)
        addView(elapsed.apply { minWidth = ui.dp(36) })
        addView(seek, LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        addView(total.apply { minWidth = ui.dp(36); gravity = Gravity.END })
    }

    private fun clock(millis: Int): String {
        val seconds = millis.coerceAtLeast(0) / 1000
        return "${seconds / 60}:${String.format(java.util.Locale.US, "%02d", seconds % 60)}"
    }

    /** Brings the icon, the handle and the times up to date. Safe to call often. */
    fun refresh() {
        val playing = source.isPlaying()
        play.setImageResource(if (playing) R.drawable.ic_pause else R.drawable.ic_play)
        play.contentDescription = if (playing) "Pause" else "Play"
        val duration = source.durationMs()
        elapsed.text = clock(source.positionMs())
        total.text = clock(duration)
        seek.fraction = if (duration > 0) source.positionMs().toFloat() / duration else 0f
    }
}
