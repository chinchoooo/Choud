package cloud.personal.sync

import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

/** Pure formatting helpers (no Android types, so they are plain JVM unit tests). */

fun fmtBytes(bytes: Long): String {
    if (bytes < 1024) return "$bytes B"
    val units = arrayOf("KB", "MB", "GB", "TB")
    var value = bytes / 1024.0
    var unit = 0
    while (value >= 1024 && unit < units.lastIndex) {
        value /= 1024
        unit++
    }
    return String.format(Locale.US, "%.1f %s", value, units[unit])
}

fun fmtSpeed(bytesPerSecond: Double): String =
    if (bytesPerSecond <= 0.0 || bytesPerSecond.isNaN()) "-" else "${fmtBytes(bytesPerSecond.toLong())}/s"

/** "42s", "3m 05s", "1h 12m"; "-" when unknown. */
fun fmtDuration(seconds: Long): String = when {
    seconds < 0 -> "-"
    seconds < 60 -> "${seconds}s"
    seconds < 3600 -> "${seconds / 60}m ${String.format(Locale.US, "%02d", seconds % 60)}s"
    else -> "${seconds / 3600}h ${String.format(Locale.US, "%02d", (seconds % 3600) / 60)}m"
}

/** Seconds left at the current speed, or null while the speed is unknown. */
fun etaSeconds(remainingBytes: Long, bytesPerSecond: Double): Long? {
    if (remainingBytes <= 0) return 0
    if (bytesPerSecond <= 0.0 || bytesPerSecond.isNaN()) return null
    return (remainingBytes / bytesPerSecond).toLong()
}

/** Exponential smoothing so the speed readout doesn't jitter. */
fun smoothSpeed(previous: Double, instantaneous: Double, alpha: Double = 0.3): Double =
    if (previous <= 0.0) instantaneous else alpha * instantaneous + (1 - alpha) * previous

/** "October 2026", used to group the photo timeline. */
fun monthLabel(millis: Long, zone: ZoneId = ZoneId.systemDefault()): String =
    if (millis <= 0) "Unknown date"
    else DateTimeFormatter.ofPattern("MMMM yyyy", Locale.getDefault()).withZone(zone).format(Instant.ofEpochMilli(millis))

fun fmtDate(millis: Long?, zone: ZoneId = ZoneId.systemDefault()): String =
    if (millis == null || millis <= 0) "-"
    else DateTimeFormatter.ofPattern("d MMM yyyy, HH:mm", Locale.getDefault()).withZone(zone).format(Instant.ofEpochMilli(millis))

/** An ISO-8601 instant for an epoch-millis time, or null when the time is unknown. */
fun isoFromMillis(millis: Long): String? =
    if (millis <= 0) null else Instant.ofEpochMilli(millis).toString()

/** One row of the photo grid: a month heading, or a photo. */
sealed interface PhotoRow {
    data class Header(val label: String) : PhotoRow
    data class Photo(val item: RemoteItem, val indexInAll: Int) : PhotoRow
}

/** Photos (already sorted newest first) with a heading wherever the month changes. */
fun groupByMonth(items: List<RemoteItem>, zone: ZoneId = ZoneId.systemDefault()): List<PhotoRow> {
    val rows = ArrayList<PhotoRow>()
    var last: String? = null
    items.forEachIndexed { index, item ->
        val label = monthLabel(item.sortMillis, zone)
        if (label != last) {
            rows += PhotoRow.Header(label)
            last = label
        }
        rows += PhotoRow.Photo(item, index)
    }
    return rows
}
