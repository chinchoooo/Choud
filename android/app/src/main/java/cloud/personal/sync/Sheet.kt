package cloud.personal.sync

import android.content.res.ColorStateList
import android.graphics.drawable.RippleDrawable
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import androidx.annotation.DrawableRes

/** One tappable line in an action sheet. */
class SheetItem(
    @DrawableRes val icon: Int?,
    val label: String,
    val detail: String? = null,
    val danger: Boolean = false,
    val onClick: () -> Unit,
)

/** The open sheet: put views in `body`, call `dismiss()` to close it. */
class SheetHandle(val body: LinearLayout, private val close: () -> Unit, private val open: () -> Boolean) {
    val isShowing: Boolean get() = open()
    fun dismiss() = close()
}

/** A full-screen page over the app: put views in `body`; Back or `dismiss()` closes it. */
class Page(val body: LinearLayout, private val close: () -> Unit, private val open: () -> Boolean) {
    val isShowing: Boolean get() = open()
    fun dismiss() = close()
}

/** A scroll area that never grows taller than a share of the screen. */
private class CappedScroll(context: android.content.Context, private val maxFraction: Float) : ScrollView(context) {
    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        val cap = (resources.displayMetrics.heightPixels * maxFraction).toInt()
        super.onMeasure(widthMeasureSpec, MeasureSpec.makeMeasureSpec(cap, MeasureSpec.AT_MOST))
    }
}

/**
 * Our own bottom sheet and confirm dialog, drawn inside the app's theme. Replaces the system
 * AlertDialog, which ignores the palette and always shows a white stock box.
 */
class Sheets(private val ui: Ui, private val container: FrameLayout) {
    private var layer: FrameLayout? = null
    private val pages = ArrayList<FrameLayout>()

    val isOpen: Boolean get() = layer != null || pages.isNotEmpty()

    /** Back pressed: closes the sheet if one is open, else the top page. */
    fun dismiss() {
        if (layer != null) closeSheet() else pages.lastOrNull()?.let { closePage(it) }
    }

    private fun closeSheet() {
        layer?.let { container.removeView(it) }
        layer = null
    }

    private fun closePage(page: FrameLayout) {
        container.removeView(page)
        pages.remove(page)
    }

    /**
     * A full-screen page with a back arrow and a title. `header` (a search field, say) sits under the
     * title bar and does not scroll.
     */
    fun page(title: String, header: View? = null): Page {
        val p = ui.palette
        val body = ui.vertical()
        lateinit var root: FrameLayout
        val bar = ui.topBar(title, onBack = { closePage(root) })
        val column = ui.vertical().apply {
            addView(bar)
            addView(ui.divider())
            if (header != null) {
                addView(header)
                addView(ui.divider())
            }
            addView(
                ScrollView(ui.context).apply {
                    isFillViewport = true
                    addView(body)
                },
                LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f),
            )
        }
        root = FrameLayout(ui.context).apply {
            setBackgroundColor(p.bg)
            isClickable = true // nothing underneath may be tapped through the page
            addView(column, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        }
        container.addView(root, ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        pages.add(root)
        return Page(body, { closePage(root) }, { pages.contains(root) })
    }

    /** Opens an empty sheet with a title; the caller fills `body`. Any open sheet is replaced. */
    fun show(title: String?, subtitle: String? = null, fill: (SheetHandle) -> Unit = {}): SheetHandle {
        closeSheet()
        val p = ui.palette
        val body = ui.vertical()
        val scroll = CappedScroll(ui.context, 0.78f).apply { addView(body) }
        val panel = ui.vertical().apply {
            isClickable = true // swallow taps so only the scrim closes the sheet
            background = panelBackground()
            setPadding(0, ui.dp(8), 0, ui.dp(12))
            if (!p.retro) {
                addView(
                    View(ui.context).apply { background = ui.box(p.line, radiusDp = 3) },
                    LinearLayout.LayoutParams(ui.dp(36), ui.dp(4)).apply {
                        gravity = Gravity.CENTER_HORIZONTAL
                        bottomMargin = ui.dp(6)
                    },
                )
            }
            if (title != null) {
                addView(
                    ui.text(title, 15f, bold = true).apply {
                        maxLines = 2
                        ellipsize = android.text.TextUtils.TruncateAt.MIDDLE
                        setPadding(ui.dp(20), ui.dp(8), ui.dp(20), if (subtitle == null) ui.dp(10) else 0)
                    },
                )
            }
            if (subtitle != null) {
                addView(ui.muted(subtitle, 12f).apply { setPadding(ui.dp(20), ui.dp(2), ui.dp(20), ui.dp(10)) })
            }
            addView(scroll, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        }
        val root = FrameLayout(ui.context).apply {
            setBackgroundColor(0x99000000.toInt())
            isClickable = true
            setOnClickListener { closeSheet() }
            addView(panel, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.BOTTOM))
        }
        container.addView(root, ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        layer = root
        if (animationsOn()) {
            root.alpha = 0f
            panel.translationY = ui.dp(48).toFloat()
            root.animate().alpha(1f).setDuration(120).start()
            panel.animate().translationY(0f).setDuration(180).start()
        }
        val handle = SheetHandle(body, { if (layer === root) closeSheet() }, { layer === root })
        fill(handle)
        return handle
    }

    /** A list of actions, each a 56 dp row. Tapping one closes the sheet first, then runs it. */
    fun actions(title: String?, subtitle: String?, items: List<SheetItem>) {
        show(title, subtitle) { sheet ->
            items.forEach { item ->
                sheet.body.addView(
                    ui.listRow(
                        leading = item.icon,
                        title = item.label,
                        subtitle = item.detail,
                        danger = item.danger,
                        chevron = false,
                    ) {
                        sheet.dismiss()
                        item.onClick()
                    },
                )
            }
        }
    }

    /** Title, message and two buttons. The destructive choice is never the default look in colour alone. */
    fun confirm(
        title: String,
        message: String,
        confirmLabel: String,
        danger: Boolean = false,
        onConfirm: () -> Unit,
    ) {
        show(title, null) { sheet ->
            sheet.body.addView(ui.muted(message, 13f).apply { setPadding(ui.dp(20), 0, ui.dp(20), ui.dp(14)) })
            sheet.body.addView(buttons(sheet, confirmLabel, danger, onConfirm))
        }
    }

    /** A "Cancel" plus one main button, to put at the bottom of a sheet. */
    fun buttons(sheet: SheetHandle, mainLabel: String, danger: Boolean = false, onMain: () -> Unit): View =
        ui.horizontal().apply {
            setPadding(ui.dp(16), ui.dp(4), ui.dp(16), ui.dp(4))
            addView(ui.button("Cancel") { sheet.dismiss() }, LinearLayout.LayoutParams(0, ui.dp(48), 1f))
            addView(View(ui.context), LinearLayout.LayoutParams(ui.dp(10), 1))
            val label = if (danger) mainLabel else mainLabel
            addView(
                ui.button(label, primary = !danger) {
                    sheet.dismiss()
                    onMain()
                }.apply {
                    if (danger) {
                        setTextColor(ui.palette.danger)
                        val base = ui.box(ui.palette.surface, ui.palette.danger)
                        background = RippleDrawable(ColorStateList.valueOf(ui.palette.line), base, null)
                    }
                },
                LinearLayout.LayoutParams(0, ui.dp(48), 1f),
            )
        }

    /**
     * The choices for how long a share link should work, with the truth about who can open it.
     * When links only work on the private network, "send the file itself" is offered first.
     */
    fun linkChoices(
        title: String,
        instance: ApiClient.Instance?,
        onSendFile: (() -> Unit)? = null,
        onPick: (hours: Int?, maxDownloads: Int?) -> Unit,
    ) {
        val everywhere = instance?.linksWorkEverywhere == true
        val note = when (instance?.publicStatus) {
            "ready" -> "Anyone who has the link can open it until it stops working."
            "paused" -> "Public links are paused: only devices on your private network can open a link."
            "not_configured" -> "Only devices on your private network can open a link. Ask the administrator to run scripts/enable-public-links.sh to make links work from anywhere."
            else -> "Anyone who can reach your server can open the link until it stops working."
        }
        val items = mutableListOf<SheetItem>()
        if (!everywhere && instance != null && onSendFile != null) {
            items += SheetItem(R.drawable.ic_download, "Send the file itself instead", "Works for anyone, no link needed") { onSendFile() }
        }
        items += listOf(
            SheetItem(R.drawable.ic_link, "Link for 1 day") { onPick(24, null) },
            SheetItem(R.drawable.ic_link, "Link for 7 days") { onPick(24 * 7, null) },
            SheetItem(R.drawable.ic_link, "One-time link", "Stops working after one open") { onPick(24 * 7, 1) },
            SheetItem(R.drawable.ic_link, "Link that never expires") { onPick(null, null) },
        )
        actions(title, note, items)
    }

    private fun panelBackground(): android.graphics.drawable.Drawable {
        val p = ui.palette
        val r = if (p.retro) 0f else ui.dp(18).toFloat()
        return android.graphics.drawable.GradientDrawable().apply {
            setColor(p.surface)
            cornerRadii = floatArrayOf(r, r, r, r, 0f, 0f, 0f, 0f)
            setStroke(ui.dp(1), if (p.retro) p.ink else p.line)
        }
    }

    private fun animationsOn(): Boolean =
        android.provider.Settings.Global.getFloat(
            ui.context.contentResolver,
            android.provider.Settings.Global.ANIMATOR_DURATION_SCALE,
            1f,
        ) > 0f
}
