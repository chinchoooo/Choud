package cloud.personal.sync

import android.content.Context
import android.util.Log
import java.io.File
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Persistent, human-readable activity log: every API call, every file step, every error.
 * Lives in the app's private storage (survives restarts, trimmed to ~400 KB) and is shown
 * on the main screen. Secrets (passwords, tokens) are never written to it.
 */
object EventLog {
    private const val MAX_BYTES = 400_000L
    private var file: File? = null
    private val stamp = SimpleDateFormat("MM-dd HH:mm:ss.SSS", Locale.US)

    @Volatile
    var version = 0
        private set

    fun init(context: Context) {
        if (file == null) file = File(context.applicationContext.filesDir, "activity.log")
    }

    @Synchronized
    fun log(message: String) {
        Log.i("PCloud", message)
        val f = file ?: return
        try {
            if (f.length() > MAX_BYTES) {
                val keep = f.readText().takeLast((MAX_BYTES / 2).toInt())
                f.writeText(keep.substringAfter('\n', keep))
            }
            f.appendText("${stamp.format(Date())}  $message\n")
            version++
        } catch (_: Exception) {
            // Logging must never break a backup.
        }
    }

    @Synchronized
    fun tail(maxChars: Int = 30_000): String =
        try {
            file?.takeIf { it.exists() }?.readText()?.takeLast(maxChars).orEmpty()
        } catch (_: Exception) {
            ""
        }

    @Synchronized
    fun clear() {
        try {
            file?.writeText("")
            version++
        } catch (_: Exception) {
        }
    }
}

data class QueueEntry(val name: String, val size: Long)

/** One finished file: ok=false means it failed; `note` says what happened. */
data class DoneEntry(val name: String, val size: Long, val ok: Boolean, val note: String)

/** A file being worked on right now (several can be in flight at once). */
class ActiveItem(val key: String, val name: String, val size: Long) {
    @Volatile var phase: String = "starting"

    /** Bytes handled in the current phase: hashed while "hashing", sent while "uploading". */
    @Volatile var bytes: Long = 0
    val startedAt: Long = System.currentTimeMillis()
}

/**
 * Everything the queue screen shows, updated by the backup worker threads and read by the UI.
 * Plain thread-safe fields: the UI polls it a couple of times a second.
 */
object LiveStatus {
    /** idle | scanning | running | stopping */
    @Volatile var phase: String = "idle"
    @Volatile var runStartedMillis: Long = 0
    @Volatile var total: Int = 0
    @Volatile var bytesTotalAll: Long = 0
    @Volatile var message: String = ""

    val done = AtomicInteger(0)
    val failed = AtomicInteger(0)

    /** The catch-up pass that puts the phone's dates on files that were backed up earlier. */
    val datesDone = AtomicInteger(0)
    @Volatile var datesTotal: Int = 0
    val bytesDoneAll = AtomicLong(0)

    /** Files being processed right now, by media key. */
    val active = ConcurrentHashMap<String, ActiveItem>()

    /** Files not started yet, in the order they will be picked up. */
    val waiting = ConcurrentLinkedQueue<QueueEntry>()

    private val recentList = ArrayList<DoneEntry>()

    @Volatile var cancelRequested: Boolean = false

    val running: Boolean get() = phase == "scanning" || phase == "running" || phase == "dates" || phase == "stopping"

    @Synchronized
    fun addRecent(entry: DoneEntry) {
        recentList.add(0, entry)
        if (recentList.size > 40) recentList.removeAt(recentList.size - 1)
    }

    @Synchronized
    fun recent(): List<DoneEntry> = ArrayList(recentList)

    fun start() {
        done.set(0)
        failed.set(0)
        datesDone.set(0)
        datesTotal = 0
        bytesDoneAll.set(0)
        total = 0
        bytesTotalAll = 0
        message = ""
        active.clear()
        waiting.clear()
        cancelRequested = false
        runStartedMillis = System.currentTimeMillis()
        phase = "scanning"
    }

    fun finish() {
        active.clear()
        waiting.clear()
        phase = "idle"
    }

    /** Bytes confirmed uploaded, plus the uploaded part of every file currently in flight. */
    fun bytesNow(): Long =
        bytesDoneAll.get() + active.values.filter { it.phase == "uploading" }.sumOf { it.bytes }
}
