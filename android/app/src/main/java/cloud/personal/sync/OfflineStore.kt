package cloud.personal.sync

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * Files kept on the phone so they open without the server (planes, bad signal, a server that is off).
 *
 * Each kept file is stored under its server id in the app's private storage; a small index remembers
 * the details (name, size, type) so the Files tab can still list them while the server is unreachable.
 * Nothing here is ever uploaded: it is a local copy only, and "Remove" just deletes that copy.
 */
object OfflineStore {
    private const val PREFS = "offline"
    private const val INDEX = "index"

    private fun dir(context: Context) = File(context.applicationContext.filesDir, "offline").apply { mkdirs() }

    private fun prefs(context: Context) = context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun file(context: Context, id: String): File? = File(dir(context), id).takeIf { it.isFile }

    fun has(context: Context, id: String) = file(context, id) != null

    /** Downloads `item` and keeps it. Returns the size. Throws on a network problem (nothing half-kept). */
    fun keep(context: Context, api: ApiClient, item: RemoteItem, onProgress: (done: Long, total: Long) -> Unit = { _, _ -> }): Long {
        val part = File(dir(context), "${item.id}.part")
        try {
            val size = api.downloadContent(item.id, part, onProgress = onProgress)
            val target = File(dir(context), item.id)
            target.delete()
            if (!part.renameTo(target)) throw java.io.IOException("could not store the file")
            writeIndex(context, readIndex(context).filter { it.id != item.id } + item)
            return size
        } finally {
            part.delete()
        }
    }

    fun remove(context: Context, id: String) {
        File(dir(context), id).delete()
        writeIndex(context, readIndex(context).filter { it.id != id })
    }

    fun clear(context: Context) {
        dir(context).listFiles()?.forEach { it.delete() }
        writeIndex(context, emptyList())
    }

    /** What is kept, newest name order, only entries whose file still exists. */
    fun items(context: Context): List<RemoteItem> =
        readIndex(context).filter { has(context, it.id) }.sortedBy { it.name.lowercase() }

    fun totalBytes(context: Context): Long =
        dir(context).listFiles()?.filter { it.isFile && !it.name.endsWith(".part") }?.sumOf { it.length() } ?: 0L

    private fun readIndex(context: Context): List<RemoteItem> {
        val raw = prefs(context).getString(INDEX, null) ?: return emptyList()
        return try {
            val array = JSONArray(raw)
            (0 until array.length()).map { i ->
                val o = array.getJSONObject(i)
                RemoteItem(
                    id = o.getString("id"),
                    name = o.getString("name"),
                    size = o.optLong("size"),
                    mime = o.optString("mime"),
                    favorite = o.optBoolean("favorite"),
                    folderPath = o.optString("folderPath"),
                    takenAtMillis = if (o.has("taken")) o.getLong("taken") else null,
                    createdAtMillis = if (o.has("created")) o.getLong("created") else null,
                    modifiedAtMillis = if (o.has("modified")) o.getLong("modified") else null,
                )
            }
        } catch (e: Exception) {
            emptyList()
        }
    }

    private fun writeIndex(context: Context, items: List<RemoteItem>) {
        val array = JSONArray()
        for (item in items) {
            array.put(
                JSONObject().apply {
                    put("id", item.id)
                    put("name", item.name)
                    put("size", item.size)
                    put("mime", item.mime)
                    put("favorite", item.favorite)
                    put("folderPath", item.folderPath)
                    item.takenAtMillis?.let { put("taken", it) }
                    item.createdAtMillis?.let { put("created", it) }
                    item.modifiedAtMillis?.let { put("modified", it) }
                },
            )
        }
        prefs(context).edit().putString(INDEX, array.toString()).apply()
    }
}
