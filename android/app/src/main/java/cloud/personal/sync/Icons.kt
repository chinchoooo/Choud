package cloud.personal.sync

import android.content.res.ColorStateList
import android.graphics.drawable.RippleDrawable
import android.view.Gravity
import android.view.ViewGroup
import android.widget.ImageView
import android.widget.LinearLayout
import androidx.annotation.DrawableRes

/** A tinted icon of the given size. */
fun Ui.icon(@DrawableRes res: Int, sizeDp: Int = 24, tint: Int = palette.ink): ImageView =
    ImageView(context).apply {
        setImageResource(res)
        imageTintList = ColorStateList.valueOf(tint)
        scaleType = ImageView.ScaleType.FIT_CENTER
        layoutParams = LinearLayout.LayoutParams(dp(sizeDp), dp(sizeDp))
    }

/** An icon over a small caption, with a press ripple and a touch target of at least 48 dp. */
fun Ui.iconButton(
    @DrawableRes res: Int,
    label: String,
    tint: Int = palette.ink,
    enabled: Boolean = true,
    onClick: () -> Unit,
): LinearLayout = LinearLayout(context).apply {
    orientation = LinearLayout.VERTICAL
    gravity = Gravity.CENTER
    minimumWidth = dp(64)
    minimumHeight = dp(52)
    setPadding(dp(6), dp(6), dp(6), dp(4))
    isClickable = enabled
    isFocusable = enabled
    contentDescription = label
    alpha = if (enabled) 1f else 0.35f
    addView(icon(res, 22, tint))
    addView(
        text(label, 10f, tint).apply {
            gravity = Gravity.CENTER
            maxLines = 1
            setPadding(0, dp(2), 0, 0)
        },
        LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT),
    )
    background = RippleDrawable(ColorStateList.valueOf(palette.line), null, null)
    if (enabled) setOnClickListener { onClick() }
}

/** A bare round icon button (no caption) for headers. */
fun Ui.iconOnly(@DrawableRes res: Int, description: String, tint: Int = palette.ink, onClick: () -> Unit): ImageView =
    ImageView(context).apply {
        setImageResource(res)
        imageTintList = ColorStateList.valueOf(tint)
        contentDescription = description
        scaleType = ImageView.ScaleType.CENTER
        setPadding(dp(12), dp(12), dp(12), dp(12))
        layoutParams = LinearLayout.LayoutParams(dp(48), dp(48))
        background = RippleDrawable(ColorStateList.valueOf(palette.line), null, null)
        isClickable = true
        isFocusable = true
        setOnClickListener { onClick() }
    }
