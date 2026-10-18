package cloud.personal.sync

import org.junit.Assert.assertEquals
import org.junit.Test

class LocalMediaTest {
    private fun item(name: String, size: Long, local: Boolean = false) = RemoteItem(
        id = if (local) "local:$name" else name, name = name, size = size, mime = "image/jpeg",
        favorite = false, folderPath = "", takenAtMillis = null, createdAtMillis = 0,
        localUri = if (local) "content://media/$name" else "",
    )

    @Test
    fun `a photo the server already has is not shown twice`() {
        val server = listOf(item("IMG_1.jpg", 100), item("IMG_2.jpg", 200))
        val phone = listOf(item("IMG_1.jpg", 100, true), item("IMG_3.jpg", 300, true))
        assertEquals(listOf("IMG_3.jpg"), LocalMedia.notOnServer(phone, server).map { it.name })
    }

    @Test
    fun `same name with a different size is a different photo`() {
        val server = listOf(item("IMG_1.jpg", 100))
        val phone = listOf(item("IMG_1.jpg", 101, true))
        assertEquals(1, LocalMedia.notOnServer(phone, server).size)
    }

    @Test
    fun `names compare without regard to case`() {
        val server = listOf(item("img_1.JPG", 100))
        val phone = listOf(item("IMG_1.jpg", 100, true))
        assertEquals(0, LocalMedia.notOnServer(phone, server).size)
    }

    @Test
    fun `an empty server library shows everything on the phone`() {
        val phone = listOf(item("a.jpg", 1, true), item("b.jpg", 2, true))
        assertEquals(2, LocalMedia.notOnServer(phone, emptyList()).size)
    }
}
