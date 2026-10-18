package cloud.personal.sync

import java.io.File
import java.security.MessageDigest

/**
 * The last answer the server gave for each listing (a folder, a page of photos), kept on disk so the
 * next visit paints from it at once and only then asks the server whether anything changed. It is a
 * cache, never a source of truth: every screen still refreshes from the server.
 */
object ListCache {
    @Volatile private var dir: File? = null

    fun init(context: android.content.Context) {
        if (dir == null) dir = File(context.applicationContext.filesDir, "lists").apply { mkdirs() }
    }

    private fun file(key: String): File? {
        val d = dir ?: return null
        val name = MessageDigest.getInstance("SHA-1").digest(key.toByteArray()).joinToString("") { "%02x".format(it) }
        return File(d, name)
    }

    fun get(key: String): String? = try {
        file(key)?.takeIf { it.isFile }?.readText()
    } catch (e: Exception) {
        null
    }

    fun put(key: String, json: String) {
        try {
            file(key)?.writeText(json)
        } catch (e: Exception) {
            EventLog.log("list cache: could not save: ${e.message}")
        }
    }

    fun clear() {
        dir?.listFiles()?.forEach { it.delete() }
    }
}
