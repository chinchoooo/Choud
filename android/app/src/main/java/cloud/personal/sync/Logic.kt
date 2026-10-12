package cloud.personal.sync

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
    val sub = relativePath.orEmpty().trim('/')
        .removePrefix("DCIM").trim('/')
        .split('/').filter { it.isNotEmpty() && it != "." && it != ".." }
        .joinToString("/")
    return "Phone Backups/${safeDeviceName(device)}/${sub.ifEmpty { "Camera" }}"
}

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
