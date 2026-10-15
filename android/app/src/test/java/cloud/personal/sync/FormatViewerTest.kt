package cloud.personal.sync

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.ZoneId
import java.time.ZonedDateTime

class FormatViewerTest {
    private val utc = ZoneId.of("UTC")

    @Test
    fun bytesAndDurations() {
        assertEquals("512 B", fmtBytes(512))
        assertEquals("1.5 KB", fmtBytes(1536))
        assertEquals("30.0 MB", fmtBytes(30L * 1024 * 1024))
        assertEquals("42s", fmtDuration(42))
        assertEquals("3m 05s", fmtDuration(185))
        assertEquals("1h 12m", fmtDuration(4320))
        assertEquals("-", fmtDuration(-1))
        assertEquals("-", fmtSpeed(0.0))
        assertEquals("2.0 KB/s", fmtSpeed(2048.0))
    }

    @Test
    fun etaOnlyWhenSpeedIsKnown() {
        assertEquals(10L, etaSeconds(1000, 100.0))
        assertNull(etaSeconds(1000, 0.0))
        assertEquals(0L, etaSeconds(0, 0.0))
    }

    @Test
    fun speedIsSmoothed() {
        assertEquals(1000.0, smoothSpeed(0.0, 1000.0), 0.001)
        assertEquals(1300.0, smoothSpeed(1000.0, 2000.0), 0.001)
    }

    private fun item(id: String, millis: Long) =
        RemoteItem(id, "$id.jpg", 1, "image/jpeg", false, "", millis, millis)

    private fun millis(year: Int, month: Int, day: Int) =
        ZonedDateTime.of(year, month, day, 12, 0, 0, 0, utc).toInstant().toEpochMilli()

    @Test
    fun photosAreGroupedWithAHeadingPerMonth() {
        val rows = groupByMonth(
            listOf(item("a", millis(2026, 10, 20)), item("b", millis(2026, 10, 2)), item("c", millis(2026, 9, 30))),
            utc,
        )
        assertEquals(5, rows.size)
        assertTrue(rows[0] is PhotoRow.Header)
        assertTrue(rows[1] is PhotoRow.Photo && (rows[1] as PhotoRow.Photo).indexInAll == 0)
        assertTrue(rows[2] is PhotoRow.Photo && (rows[2] as PhotoRow.Photo).indexInAll == 1)
        assertTrue(rows[3] is PhotoRow.Header)
        assertTrue(rows[4] is PhotoRow.Photo && (rows[4] as PhotoRow.Photo).indexInAll == 2)
        assertEquals((rows[0] as PhotoRow.Header).label.contains("2026"), true)
    }

    @Test
    fun sortMillisPrefersTakenDate() {
        val taken = RemoteItem("x", "x.jpg", 1, "image/jpeg", false, "", 1000L, 9000L)
        val uploadedOnly = RemoteItem("y", "y.jpg", 1, "image/jpeg", false, "", null, 9000L)
        assertEquals(1000L, taken.sortMillis)
        assertEquals(9000L, uploadedOnly.sortMillis)
    }

    @Test
    fun standardFormatsUseTheBuiltInViewers() {
        assertEquals(ViewerKind.IMAGE, viewerKind("a.jpg", "image/jpeg"))
        assertEquals(ViewerKind.VIDEO, viewerKind("a.mp4", "video/mp4"))
        assertEquals(ViewerKind.AUDIO, viewerKind("a.mp3", "audio/mpeg"))
        assertEquals(ViewerKind.PDF, viewerKind("a.pdf", "application/pdf"))
        assertEquals(ViewerKind.TEXT, viewerKind("notes.txt", "text/plain"))
        assertEquals(ViewerKind.TEXT, viewerKind("main.kt", null))
        assertEquals(ViewerKind.IMAGE, viewerKind("IMG_1.PNG", "application/octet-stream"))
    }

    @Test
    fun onlyUnknownFormatsGoToAnotherApp() {
        assertEquals(ViewerKind.OTHER, viewerKind("archive.zip", "application/zip"))
        assertEquals(ViewerKind.OTHER, viewerKind("README", null))
        assertEquals(ViewerKind.OTHER, viewerKind("doc.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))
    }

    @Test
    fun svgIsNeverRenderedByTheApp() {
        assertEquals(ViewerKind.OTHER, viewerKind("logo.svg", "image/svg+xml"))
        assertEquals(ViewerKind.OTHER, viewerKind("logo.svg", null))
    }

    @Test
    fun typeBadges() {
        assertEquals("PDF", typeBadge("a.pdf"))
        assertEquals("FILE", typeBadge("Makefile"))
        assertEquals("GZ", typeBadge("a.tar.gz"))
    }

    @Test
    fun themesAreFoundByIdWithALightFallback() {
        assertEquals(AppTheme.RETRO, AppTheme.fromId("retro"))
        assertEquals(AppTheme.RETRO_PAPER, AppTheme.fromId("retro-paper"))
        assertEquals(AppTheme.LIGHT, AppTheme.fromId("nonsense"))
        assertEquals(AppTheme.LIGHT, AppTheme.fromId(null))
    }
}
