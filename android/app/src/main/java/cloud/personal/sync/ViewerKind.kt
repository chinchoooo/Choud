package cloud.personal.sync

/** Which of the app's own viewers shows a file. `OTHER` falls back to another app. */
enum class ViewerKind { IMAGE, VIDEO, AUDIO, PDF, TEXT, OTHER }

private val IMAGE_EXT = setOf("png", "jpg", "jpeg", "gif", "webp", "bmp", "heic", "heif")
private val VIDEO_EXT = setOf("mp4", "webm", "mov", "m4v", "3gp", "mkv", "ogv")
private val AUDIO_EXT = setOf("mp3", "m4a", "aac", "ogg", "oga", "wav", "flac", "opus")
private val TEXT_EXT = setOf(
    "txt", "md", "markdown", "log", "csv", "tsv", "json", "yaml", "yml", "toml", "ini", "cfg",
    "conf", "env", "xml", "html", "htm", "css", "js", "mjs", "ts", "tsx", "jsx", "py", "rb", "go",
    "rs", "java", "kt", "c", "h", "cpp", "hpp", "cs", "sh", "bash", "ps1", "bat", "sql", "tex",
)

private fun extensionOf(name: String): String {
    val dot = name.lastIndexOf('.')
    return if (dot <= 0) "" else name.substring(dot + 1).lowercase()
}

/**
 * The built-in viewer for a file. The app shows everything standard itself (images, video,
 * audio, PDF, text/code) and only hands a file to another app when it is none of those.
 * SVG is deliberately not an image here: it can carry script, so it is treated as "other".
 */
fun viewerKind(name: String, mime: String?): ViewerKind {
    val type = (mime ?: "").substringBefore(';').trim().lowercase()
    val ext = extensionOf(name)
    if (type.startsWith("image/svg") || ext == "svg") return ViewerKind.OTHER
    return when {
        type.startsWith("image/") -> ViewerKind.IMAGE
        type.startsWith("video/") -> ViewerKind.VIDEO
        type.startsWith("audio/") -> ViewerKind.AUDIO
        type == "application/pdf" -> ViewerKind.PDF
        type.startsWith("text/") || type == "application/json" || type == "application/xml" -> ViewerKind.TEXT
        ext in TEXT_EXT -> ViewerKind.TEXT
        ext in IMAGE_EXT -> ViewerKind.IMAGE
        ext in VIDEO_EXT -> ViewerKind.VIDEO
        ext in AUDIO_EXT -> ViewerKind.AUDIO
        ext == "pdf" -> ViewerKind.PDF
        else -> ViewerKind.OTHER
    }
}

/** A short badge label such as "PDF", "MP4" or "DIR" for places without a thumbnail. */
fun typeBadge(name: String): String = extensionOf(name).ifEmpty { "file" }.take(4).uppercase()
