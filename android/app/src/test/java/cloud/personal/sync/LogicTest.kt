package cloud.personal.sync

import org.junit.Assert.assertEquals
import org.junit.Test

class LogicTest {
    @Test
    fun cameraFilesGoUnderAPerDeviceFolder() {
        assertEquals("Phone Backups/Pixel 8/Camera", remoteFolderFor("Pixel 8", "DCIM/Camera/"))
        assertEquals("Phone Backups/Pixel 8/Camera", remoteFolderFor("Pixel 8", "DCIM/"))
        assertEquals("Phone Backups/Pixel 8/Camera", remoteFolderFor("Pixel 8", null))
        assertEquals("Phone Backups/Pixel 8/Screenshots/2026", remoteFolderFor("Pixel 8", "DCIM/Screenshots/2026/"))
    }

    @Test
    fun twoPhonesNeverShareAFolder() {
        assertEquals(false, remoteFolderFor("A", "DCIM/Camera/") == remoteFolderFor("B", "DCIM/Camera/"))
    }

    @Test
    fun hostileDeviceNamesAndPathsCannotEscape() {
        assertEquals("Phone Backups/_/Camera", remoteFolderFor("../", "DCIM/Camera/"))
        assertEquals("Phone", safeDeviceName("   "))
        assertEquals("a_b", safeDeviceName("a/b"))
        assertEquals("Phone Backups/x/etc", remoteFolderFor("x", "DCIM/../../etc/"))
        assertEquals("a_b.jpg", safeFileName("a/b.jpg"))
    }

    @Test
    fun conflictCopyNames() {
        assertEquals("IMG_1.conflict-2026-10-17.jpg", conflictName("IMG_1.jpg", "2026-10-17"))
        assertEquals("README.conflict-2026-10-17", conflictName("README", "2026-10-17"))
        assertEquals(".bashrc.conflict-2026-10-17", conflictName(".bashrc", "2026-10-17"))
    }

    @Test
    fun chunkMath() {
        assertEquals(0, chunkCount(0, 5))
        assertEquals(1, chunkCount(5, 5))
        assertEquals(2, chunkCount(6, 5))
    }
}
