package cloud.personal.sync

import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

/** Pure decisions, kept free of Android types so they run as plain JVM unit tests. */

const val CHUNKED_THRESHOLD = 20L * 1024 * 1024
const val CHUNK_SIZE = 5L * 1024 * 1024

/** A device name safe to use as a single server folder name. */
fun safeDeviceName(raw: String): String {
    val cleaned = raw.replace(Regex("[\\\\/:*?\"<>|]"), "_").trim().trim('.')
    return cleaned.ifEmpty { "Phone" }
}

/**
 * Where a camera-roll file lands on the server. Always under a per-device folder, so two
 * phones that both have IMG_0001.jpg never collide (docs/mobile.md, problem 1).
 * `relativePath` is MediaStore's, e.g. "DCIM/Camera/".
 */
fun remoteFolderFor(device: String, relativePath: String?): String {
    val rel = relativePath.orEmpty().trim('/')
    // The camera roll keeps its short historical layout ("DCIM/Camera" -> "Camera"); any other
    // folder (Pictures/Screenshots, a messenger's media folder...) keeps its full path.
    val inside = if (rel == "DCIM" || rel.startsWith("DCIM/")) rel.removePrefix("DCIM") else rel
    val sub = inside.trim('/')
        .split('/').filter { it.isNotEmpty() && it != "." && it != ".." }
        .joinToString("/")
    return "Phone Backups/${safeDeviceName(device)}/${sub.ifEmpty { "Camera" }}"
}

/** What is backed up until the user chooses otherwise: the camera roll. */
val DEFAULT_BACKUP_PREFIXES: Set<String> = setOf("DCIM/")

/** "Pictures/Screenshots" -> "Pictures/Screenshots/": the form used to compare folder paths. */
fun normalizePrefix(path: String): String {
    val trimmed = path.trim().trim('/').trim()
    return if (trimmed.isEmpty()) "" else "$trimmed/"
}

/** Is a file whose MediaStore folder is `relativePath` inside one of the chosen folders? */
fun isSelected(relativePath: String?, prefixes: Set<String>): Boolean {
    val folder = normalizePrefix(relativePath.orEmpty())
    return folder.isNotEmpty() && prefixes.any { folder.startsWith(it) }
}

/** Changes when a file is edited in place (same MediaStore id, new size or modified time). */
fun fingerprint(size: Long, modifiedSeconds: Long): String = "$size:$modifiedSeconds"

/**
 * Does a file still need uploading? Never-uploaded files do; so do files edited since they
 * were uploaded. Rows from before fingerprints existed (null) are left alone rather than
 * re-uploading the whole library.
 */
fun needsBackup(status: String?, storedFingerprint: String?, current: String): Boolean =
    status != "done" || (storedFingerprint != null && storedFingerprint != current)

/** `name.ext` -> `name.conflict-2026-10-17.ext`, the same scheme as the desktop client. */
fun conflictName(name: String, isoDate: String): String {
    val dot = name.lastIndexOf('.')
    return if (dot <= 0) "$name.conflict-$isoDate"
    else "${name.substring(0, dot)}.conflict-$isoDate${name.substring(dot)}"
}

fun chunkCount(size: Long, chunkSize: Long): Int =
    if (size <= 0) 0 else ((size + chunkSize - 1) / chunkSize).toInt()

/** A server file name must not contain path separators (it is never used as a path). */
fun safeFileName(name: String): String =
    name.replace('/', '_').replace('\\', '_').ifBlank { "unnamed" }


// ----------------------------------------------------------------------------------------
// Dates from file names. Phone cameras write the moment of capture into the name, e.g.
// IMG_20250206_160717396.jpg (6 Feb 2025, 16:07:17.396), PXL_20250206_160717396.jpg,
// VID_20250206_160717.mp4, Screenshot_2025-02-06-16-07-17.png. That is far more trustworthy
// than a file's modified time, which becomes "the day it was copied" the moment a file is moved
// between phones, so the name wins and the file's own timestamps are the fallback.

private val COMPACT_TIME = Regex("""(?<!\d)((?:19|20)\d{2})(\d{2})(\d{2})[_\-. T]?(\d{2})(\d{2})(\d{2})(\d{3})?(?!\d)""")
private val DASHED_TIME = Regex("""(?<!\d)((?:19|20)\d{2})-(\d{2})-(\d{2})[-_ T.](\d{2})[-.:](\d{2})[-.:](\d{2})(?!\d)""")
private val COMPACT_DATE = Regex("""(?<!\d)((?:19|20)\d{2})(\d{2})(\d{2})(?!\d)""")
private val DASHED_DATE = Regex("""(?<!\d)((?:19|20)\d{2})-(\d{2})-(\d{2})(?!\d)""")

/**
 * The capture time written into a photo or video's file name (epoch millis), or null when
 * the name has none. Times in names are the phone's local time. Date-only names (such as
 * WhatsApp's IMG-20250206-WA0001.jpg) get 12:00. Impossible dates (month 13), dates before 1990
 * and dates in the future are ignored.
 */
fun dateFromFileName(
    name: String,
    zone: java.time.ZoneId = java.time.ZoneId.systemDefault(),
    nowMillis: Long = System.currentTimeMillis(),
): Long? {
    fun build(m: MatchResult, hasTime: Boolean): Long? = try {
        val g = m.groupValues
        val date = java.time.LocalDate.of(g[1].toInt(), g[2].toInt(), g[3].toInt())
        val time = if (hasTime) {
            val millis = g.getOrNull(7)?.takeIf { it.isNotEmpty() }?.toInt() ?: 0
            java.time.LocalTime.of(g[4].toInt(), g[5].toInt(), g[6].toInt(), millis * 1_000_000)
        } else {
            java.time.LocalTime.NOON
        }
        date.atTime(time).atZone(zone).toInstant().toEpochMilli()
    } catch (_: java.time.DateTimeException) {
        null
    }

    val candidates = sequence {
        COMPACT_TIME.findAll(name).forEach { yield(build(it, true)) }
        DASHED_TIME.findAll(name).forEach { yield(build(it, true)) }
        COMPACT_DATE.findAll(name).forEach { yield(build(it, false)) }
        DASHED_DATE.findAll(name).forEach { yield(build(it, false)) }
    }
    val earliest = java.time.LocalDate.of(1990, 1, 1).atStartOfDay(zone).toInstant().toEpochMilli()
    val latest = nowMillis + 24L * 3600 * 1000
    return candidates.filterNotNull().firstOrNull { it in earliest..latest }
}

/** Adds a missing http://, drops a trailing slash, and rejects things that cannot be an address. */
fun cleanAddress(raw: String): String? {
    var text = raw.trim().trimEnd('/')
    if (text.isEmpty()) return null
    if (!text.contains("://")) text = "http://$text"
    val parsed = text.toHttpUrlOrNull() ?: return null
    return parsed.toString().trimEnd('/')
}
