package cloud.personal.sync

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Base64

class ThumbHashTest {
    // Made by the server's encoder for a 64x32 image: left half red, right half blue.
    private val twoTone = "l7YCtJ54iIh4d4hwh3ePiPeIeA=="

    private fun px(rgba: ThumbHash.Rgba, x: Int, y: Int): Triple<Int, Int, Int> {
        val p = rgba.pixels[y * rgba.width + x]
        return Triple((p shr 16) and 255, (p shr 8) and 255, p and 255)
    }

    @Test
    fun `decodes the server hash to the same shape and colours`() {
        val rgba = ThumbHash.decode(Base64.getDecoder().decode(twoTone))!!
        assertEquals(32, rgba.width)
        assertEquals(18, rgba.height)
        val (lr, _, lb) = px(rgba, 2, rgba.height / 2)
        val (rr, _, rb) = px(rgba, rgba.width - 3, rgba.height / 2)
        assertTrue("left should be red, was $lr/$lb", lr > 180 && lb < 90)
        assertTrue("right should be blue, was $rr/$rb", rb > 180 && rr < 90)
    }

    @Test
    fun `aspect ratio follows the image`() {
        val landscape = Base64.getDecoder().decode(twoTone)
        assertTrue(ThumbHash.aspectRatio(landscape) > 1f)
    }

    @Test
    fun `short or empty hashes decode to nothing instead of crashing`() {
        assertNull(ThumbHash.decode(ByteArray(0)))
        assertNull(ThumbHash.decode(ByteArray(3)))
    }
}
