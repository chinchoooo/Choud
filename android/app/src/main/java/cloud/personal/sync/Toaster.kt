package cloud.personal.sync

import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.LinearLayout

/**
 * A message pill at the bottom of the screen, with an optional action such as "Undo".
 * Replaces the system Toast, which cannot carry an action and is easy to miss.
 */
class Toaster(private val ui: Ui, private val container: FrameLayout) {
    private val handler = Handler(Looper.getMainLooper())
    private var current: View? = null
    private val hide = Runnable { dismiss() }

    fun show(text: String, actionLabel: String? = null, onAction: (() -> Unit)? = null, seconds: Long = 5) {
        dismiss()
        val p = ui.palette
        val pill = LinearLayout(ui.context).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(ui.dp(16), ui.dp(10), ui.dp(8), ui.dp(10))
            // Inverted from the page so it always stands out, in every theme.
            background = ui.box(p.ink, null, radiusDp = if (p.retro) 0 else 12)
            elevation = ui.dp(6).toFloat()
            isClickable = true
            addView(
                ui.text(text, 13f, p.bg).apply { maxLines = 3 },
                LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f),
            )
            if (actionLabel != null && onAction != null) {
                addView(
                    ui.text(if (p.retro) actionLabel.uppercase() else actionLabel, 13f, p.bg, bold = true).apply {
                        setPadding(ui.dp(14), ui.dp(8), ui.dp(10), ui.dp(8))
                        setOnClickListener {
                            dismiss()
                            onAction()
                        }
                    },
                )
            }
        }
        val params = FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.WRAP_CONTENT,
            Gravity.BOTTOM,
        ).apply {
            setMargins(ui.dp(12), 0, ui.dp(12), ui.dp(12))
        }
        container.addView(pill, params)
        if (animationsOn()) {
            pill.alpha = 0f
            pill.translationY = ui.dp(16).toFloat()
            pill.animate().alpha(1f).translationY(0f).setDuration(160).start()
        }
        current = pill
        handler.postDelayed(hide, seconds * 1000)
    }

    fun dismiss() {
        handler.removeCallbacks(hide)
        current?.let { container.removeView(it) }
        current = null
    }

    private fun animationsOn(): Boolean =
        android.provider.Settings.Global.getFloat(
            ui.context.contentResolver,
            android.provider.Settings.Global.ANIMATOR_DURATION_SCALE,
            1f,
        ) > 0f
}
