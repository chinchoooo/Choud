package cloud.personal.sync

import android.graphics.Bitmap
import android.util.Base64
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/**
 * Decodes a ThumbHash (the ~25-byte blurry stand-in the server stores for every photo; a port of the
 * MIT-licensed reference by Evan Wallace) into a tiny bitmap. The grid paints this the instant a
 * cell appears, so a screenful of photos is never a screenful of grey boxes while thumbnails load.
 */
object ThumbHash {
    class Rgba(val width: Int, val height: Int, val pixels: IntArray)

    private val cache = object : android.util.LruCache<String, Bitmap>(4 * 1024 * 1024) {
        override fun sizeOf(key: String, value: Bitmap) = value.byteCount
    }

    /** A ready-to-draw bitmap for a base64 hash, or null if the hash is empty or damaged. */
    fun bitmap(base64: String): Bitmap? {
        if (base64.isEmpty()) return null
        cache.get(base64)?.let { return it }
        val bytes = try {
            Base64.decode(base64, Base64.DEFAULT)
        } catch (e: IllegalArgumentException) {
            return null
        }
        val rgba = try {
            decode(bytes)
        } catch (e: Exception) {
            null
        } ?: return null
        val bitmap = Bitmap.createBitmap(rgba.pixels, rgba.width, rgba.height, Bitmap.Config.ARGB_8888)
        cache.put(base64, bitmap)
        return bitmap
    }

    fun aspectRatio(hash: ByteArray): Float {
        val hasAlpha = (hash[2].toInt() and 0x80) != 0
        val lMax = if (hasAlpha) 5 else 7
        val lMin = hash[3].toInt() and 7
        val isLandscape = (hash[4].toInt() and 0x80) != 0
        val lx = if (isLandscape) lMax else lMin
        val ly = if (isLandscape) lMin else lMax
        return lx.toFloat() / ly
    }

    /** Pure decode (no Android types besides the result holder), so it can be unit tested. */
    fun decode(hash: ByteArray): Rgba? {
        if (hash.size < 5) return null
        fun b(i: Int) = hash[i].toInt() and 0xFF
        val header24 = b(0) or (b(1) shl 8) or (b(2) shl 16)
        val header16 = b(3) or (b(4) shl 8)
        val lDc = (header24 and 63) / 63f
        val pDc = ((header24 shr 6) and 63) / 31.5f - 1
        val qDc = ((header24 shr 12) and 63) / 31.5f - 1
        val lScale = ((header24 shr 18) and 31) / 31f
        val hasAlpha = (header24 shr 23) != 0
        val pScale = ((header16 shr 3) and 63) / 63f
        val qScale = ((header16 shr 9) and 63) / 63f
        val isLandscape = (header16 shr 15) != 0
        val lx = max(3, if (isLandscape) (if (hasAlpha) 5 else 7) else header16 and 7)
        val ly = max(3, if (isLandscape) header16 and 7 else (if (hasAlpha) 5 else 7))
        val aDc = if (hasAlpha) (b(5) and 15) / 15f else 1f
        val aScale = if (hasAlpha) (b(5) shr 4) / 15f else 0f

        val acStart = if (hasAlpha) 6 else 5
        var acIndex = 0
        fun channel(nx: Int, ny: Int, scale: Float): FloatArray {
            val out = ArrayList<Float>()
            for (cy in 0 until ny) {
                var cx = if (cy > 0) 0 else 1
                while (cx * ny < nx * (ny - cy)) {
                    val byteIndex = acStart + (acIndex shr 1)
                    if (byteIndex >= hash.size) return out.toFloatArray()
                    out.add((((b(byteIndex) shr ((acIndex and 1) shl 2)) and 15) / 7.5f - 1) * scale)
                    acIndex++
                    cx++
                }
            }
            return out.toFloatArray()
        }

        val lAc = channel(lx, ly, lScale)
        val pAc = channel(3, 3, pScale * 1.25f)
        val qAc = channel(3, 3, qScale * 1.25f)
        val aAc = if (hasAlpha) channel(5, 5, aScale) else FloatArray(0)

        val ratio = aspectRatio(hash)
        val w = (if (ratio > 1) 32f else 32f * ratio).roundToInt().coerceAtLeast(1)
        val h = (if (ratio > 1) 32f / ratio else 32f).roundToInt().coerceAtLeast(1)
        val pixels = IntArray(w * h)
        val fx = FloatArray(max(lx, if (hasAlpha) 5 else 3))
        val fy = FloatArray(max(ly, if (hasAlpha) 5 else 3))
        var i = 0
        for (y in 0 until h) {
            for (x in 0 until w) {
                var l = lDc
                var p = pDc
                var q = qDc
                var a = aDc
                for (cx in fx.indices) fx[cx] = cos(PI / w * (x + 0.5) * cx).toFloat()
                for (cy in fy.indices) fy[cy] = cos(PI / h * (y + 0.5) * cy).toFloat()

                var j = 0
                for (cy in 0 until ly) {
                    var cx = if (cy > 0) 0 else 1
                    val fy2 = fy[cy] * 2
                    while (cx * ly < lx * (ly - cy)) {
                        if (j < lAc.size) l += lAc[j] * fx[cx] * fy2
                        cx++
                        j++
                    }
                }
                j = 0
                for (cy in 0 until 3) {
                    var cx = if (cy > 0) 0 else 1
                    val fy2 = fy[cy] * 2
                    while (cx < 3 - cy) {
                        val f = fx[cx] * fy2
                        if (j < pAc.size) p += pAc[j] * f
                        if (j < qAc.size) q += qAc[j] * f
                        cx++
                        j++
                    }
                }
                if (hasAlpha) {
                    j = 0
                    for (cy in 0 until 5) {
                        var cx = if (cy > 0) 0 else 1
                        val fy2 = fy[cy] * 2
                        while (cx < 5 - cy) {
                            if (j < aAc.size) a += aAc[j] * fx[cx] * fy2
                            cx++
                            j++
                        }
                    }
                }
                val blue = l - 2f / 3f * p
                val red = (3f * l - blue + q) / 2f
                val green = red - q
                fun c(v: Float) = max(0, min(255, (255f * v).roundToInt()))
                pixels[i++] = (c(a) shl 24) or (c(red) shl 16) or (c(green) shl 8) or c(blue)
            }
        }
        return Rgba(w, h, pixels)
    }
}
