package cloud.personal.sync

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test
import java.nio.ByteBuffer
import java.util.UUID

class ThumbFramesTest {
    private fun frame(id: UUID, status: Int, payload: ByteArray): ByteArray {
        val buffer = ByteBuffer.allocate(21 + payload.size)
        buffer.putLong(id.mostSignificantBits).putLong(id.leastSignificantBits)
        buffer.put(status.toByte()).putInt(payload.size).put(payload)
        return buffer.array()
    }

    @Test
    fun `parses a run of frames in order`() {
        val a = UUID.randomUUID()
        val b = UUID.randomUUID()
        val data = frame(a, 0, byteArrayOf(1, 2, 3)) + frame(b, 2, ByteArray(0))
        val frames = parseThumbFrames(data)
        assertEquals(2, frames.size)
        assertEquals(a.toString(), frames[0].id)
        assertEquals(0, frames[0].status)
        assertArrayEquals(byteArrayOf(1, 2, 3), frames[0].bytes)
        assertEquals(b.toString(), frames[1].id)
        assertEquals(2, frames[1].status)
        assertEquals(0, frames[1].bytes.size)
    }

    @Test
    fun `a cut-off answer keeps the frames that arrived whole`() {
        val a = UUID.randomUUID()
        val b = UUID.randomUUID()
        val whole = frame(a, 0, byteArrayOf(9, 9)) + frame(b, 0, ByteArray(50) { 7 })
        val frames = parseThumbFrames(whole.copyOf(whole.size - 10))
        assertEquals(1, frames.size)
        assertEquals(a.toString(), frames[0].id)
    }

    @Test
    fun `empty or tiny input gives nothing`() {
        assertEquals(0, parseThumbFrames(ByteArray(0)).size)
        assertEquals(0, parseThumbFrames(ByteArray(10)).size)
    }
}
