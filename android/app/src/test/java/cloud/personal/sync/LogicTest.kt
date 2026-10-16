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
    fun otherFoldersKeepTheirFullPathUnderTheDevice() {
        assertEquals("Phone Backups/P/Pictures/Screenshots", remoteFolderFor("P", "Pictures/Screenshots/"))
        assertEquals("Phone Backups/P/Movies", remoteFolderFor("P", "Movies/"))
        // a folder merely starting with "DCIM" is not the camera roll
        assertEquals("Phone Backups/P/DCIM2/x", remoteFolderFor("P", "DCIM2/x/"))
    }

    @Test
    fun folderSelectionMatchesWholeFoldersAndTheirChildren() {
        val chosen = setOf("DCIM/", "Pictures/Screenshots/")
        assertEquals(true, isSelected("DCIM/Camera/", chosen))
        assertEquals(true, isSelected("DCIM/", chosen))
        assertEquals(true, isSelected("Pictures/Screenshots/2026/", chosen))
        assertEquals(false, isSelected("Pictures/", chosen))
        assertEquals(false, isSelected("DCIM2/", chosen))
        assertEquals(false, isSelected(null, chosen))
        assertEquals("Pictures/Screenshots/", normalizePrefix("/Pictures/Screenshots"))
        assertEquals("", normalizePrefix("  / "))
        assertEquals(setOf("DCIM/"), DEFAULT_BACKUP_PREFIXES)
    }

    @Test
    fun editedFilesAreUploadedAgainButOldRowsAreLeftAlone() {
        val now = fingerprint(100, 1_700_000_000)
        assertEquals(true, needsBackup(null, null, now))          // never uploaded
        assertEquals(true, needsBackup("failed", null, now))      // failed before
        assertEquals(true, needsBackup("uploading", null, now))   // interrupted
        assertEquals(false, needsBackup("done", now, now))        // unchanged
        assertEquals(true, needsBackup("done", fingerprint(90, 1_700_000_000), now)) // edited
        assertEquals(false, needsBackup("done", null, now))       // uploaded before fingerprints existed
    }

    private val utc = java.time.ZoneId.of("UTC")
    private fun at(y: Int, mo: Int, d: Int, h: Int = 12, mi: Int = 0, s: Int = 0, ms: Int = 0) =
        java.time.ZonedDateTime.of(y, mo, d, h, mi, s, ms * 1_000_000, utc).toInstant().toEpochMilli()

    @Test
    fun cameraFileNamesCarryTheCaptureTime() {
        assertEquals(at(2025, 2, 6, 16, 7, 17, 396), dateFromFileName("IMG_20250206_160717396.jpg", utc))
        assertEquals(at(2025, 2, 6, 16, 7, 17, 396), dateFromFileName("PXL_20250206_160717396.jpg", utc))
        assertEquals(at(2025, 2, 6, 16, 7, 17), dateFromFileName("VID_20250206_160717.mp4", utc))
        assertEquals(at(2025, 2, 6, 16, 7, 17), dateFromFileName("Screenshot_20250206-160717.png", utc))
        assertEquals(at(2025, 2, 6, 16, 7, 17), dateFromFileName("Screenshot_2025-02-06-16-07-17.png", utc))
        assertEquals(at(2025, 2, 6, 16, 7, 17), dateFromFileName("2025-02-06 16.07.17.jpg", utc))
    }

    @Test
    fun aNameThatRepeatsItselfStillParses() {
        assertEquals(
            at(2025, 2, 6, 16, 7, 17, 396),
            dateFromFileName("IMG_20250206_160717396.jpgIMG_20250206_160717396.jpg", utc),
        )
    }

    @Test
    fun dateOnlyNamesGetNoon() {
        assertEquals(at(2025, 2, 6), dateFromFileName("IMG-20250206-WA0001.jpg", utc))
        assertEquals(at(2024, 12, 31), dateFromFileName("photo_2024-12-31.jpg", utc))
    }

    @Test
    fun namesWithoutARealDateAreIgnored() {
        assertEquals(null, dateFromFileName("holiday.jpg", utc))
        assertEquals(null, dateFromFileName("IMG_1234.jpg", utc))
        assertEquals(null, dateFromFileName("IMG_20251399_251717.jpg", utc))        // month 13
        assertEquals(null, dateFromFileName("scan_18991231_000000.jpg", utc))       // before 1990
        assertEquals(null, dateFromFileName("IMG_20990101_000000.jpg", utc, nowMillis = at(2026, 1, 1))) // future
        assertEquals(null, dateFromFileName("file_123420250206160717999999.jpg", utc)) // digits run on
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
