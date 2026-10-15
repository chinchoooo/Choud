package cloud.personal.sync

import android.content.Context
import android.graphics.Matrix
import android.graphics.RectF
import android.view.GestureDetector
import android.view.MotionEvent
import android.view.ScaleGestureDetector
import android.widget.ImageView

/** An image you can pinch to zoom, drag around and double-tap. Starts "fit to screen". */
class ZoomImageView(context: Context) : ImageView(context) {
    private val matrixValues = FloatArray(9)
    private val drawMatrix = Matrix()
    private var fitScale = 1f
    private var scale = 1f
    private val maxZoom = 6f

    val isZoomed: Boolean get() = scale > fitScale * 1.02f

    private val scaleDetector = ScaleGestureDetector(
        context,
        object : ScaleGestureDetector.SimpleOnScaleGestureListener() {
            override fun onScale(detector: ScaleGestureDetector): Boolean {
                zoomBy(detector.scaleFactor, detector.focusX, detector.focusY)
                return true
            }
        },
    )

    private val gestures = GestureDetector(
        context,
        object : GestureDetector.SimpleOnGestureListener() {
            override fun onDown(e: MotionEvent) = true

            override fun onScroll(e1: MotionEvent?, e2: MotionEvent, dx: Float, dy: Float): Boolean {
                if (!isZoomed) return false
                drawMatrix.postTranslate(-dx, -dy)
                clampTranslation()
                imageMatrix = drawMatrix
                return true
            }

            override fun onDoubleTap(e: MotionEvent): Boolean {
                if (isZoomed) fitToScreen() else zoomBy(3f, e.x, e.y)
                return true
            }
        },
    )

    init {
        scaleType = ScaleType.MATRIX
    }

    override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
        super.onSizeChanged(w, h, oldw, oldh)
        fitToScreen()
    }

    override fun setImageBitmap(bm: android.graphics.Bitmap?) {
        super.setImageBitmap(bm)
        fitToScreen()
    }

    fun fitToScreen() {
        val d = drawable ?: return
        if (width == 0 || height == 0 || d.intrinsicWidth <= 0 || d.intrinsicHeight <= 0) return
        fitScale = minOf(width.toFloat() / d.intrinsicWidth, height.toFloat() / d.intrinsicHeight)
        scale = fitScale
        drawMatrix.reset()
        drawMatrix.postScale(fitScale, fitScale)
        drawMatrix.postTranslate(
            (width - d.intrinsicWidth * fitScale) / 2f,
            (height - d.intrinsicHeight * fitScale) / 2f,
        )
        imageMatrix = drawMatrix
    }

    private fun zoomBy(factor: Float, px: Float, py: Float) {
        val target = (scale * factor).coerceIn(fitScale, fitScale * maxZoom)
        val applied = target / scale
        drawMatrix.postScale(applied, applied, px, py)
        scale = target
        clampTranslation()
        imageMatrix = drawMatrix
    }

    /** Keeps the picture from being dragged off-screen; centres it when it is smaller than the view. */
    private fun clampTranslation() {
        val d = drawable ?: return
        val rect = RectF(0f, 0f, d.intrinsicWidth.toFloat(), d.intrinsicHeight.toFloat())
        drawMatrix.mapRect(rect)
        var dx = 0f
        var dy = 0f
        if (rect.width() <= width) dx = (width - rect.width()) / 2f - rect.left
        else if (rect.left > 0) dx = -rect.left
        else if (rect.right < width) dx = width - rect.right
        if (rect.height() <= height) dy = (height - rect.height()) / 2f - rect.top
        else if (rect.top > 0) dy = -rect.top
        else if (rect.bottom < height) dy = height - rect.bottom
        drawMatrix.postTranslate(dx, dy)
        drawMatrix.getValues(matrixValues)
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        scaleDetector.onTouchEvent(event)
        gestures.onTouchEvent(event)
        // While zoomed, keep the gesture so a parent doesn't steal the drag.
        parent?.requestDisallowInterceptTouchEvent(isZoomed || event.pointerCount > 1)
        return true
    }
}
