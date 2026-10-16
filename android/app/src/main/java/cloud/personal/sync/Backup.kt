package cloud.personal.sync

import android.content.ContentResolver
import android.content.ContentUris
import android.content.Context
import android.net.Uri
import android.provider.MediaStore
import java.io.IOException
import java.time.Instant
import java.time.LocalDate
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

data class BackupSummary(val uploaded: Int, val skipped: Int, val failed: Int)

data class MediaItem(
    val key: String,
    val uri: Uri,
    val name: String,
    val size: Long,
    val mime: String,
    val relativePath: String?,
    /** When the photo/video was taken (or last modified), in epoch millis; 0 if unknown. */
    val takenAtMillis: Long = 0,
    /** Changes when the file is edited in place, so an edited photo is uploaded again. */
    val fp: String = "",
    /** The phone's own last-modified time, in epoch millis (0 if unknown). */
    val modifiedMillis: Long = 0,
)

/** Files uploaded at the same time. Small photos are latency-bound, so several at once is much faster. */
const val PARALLEL_UPLOADS = 3

/**
 * One-way camera-roll backup (phone -> server). It never downloads into the camera roll and
 * never deletes anything on the phone (docs/mobile.md, problem 1).
 */
class CameraBackup(
    private val context: Context,
    private val settings: Settings,
    private val db: BackupDb,
    private val api: ApiClient,
    private val log: (String) -> Unit = {},
    private val shouldStop: () -> Boolean = { false },
) {
    private val folderIds = HashMap<String, String>()

    private fun query(collection: Uri, prefix: String, selected: Set<String>): List<MediaItem> {
        val projection = arrayOf(
            MediaStore.MediaColumns._ID,
            MediaStore.MediaColumns.DISPLAY_NAME,
            MediaStore.MediaColumns.SIZE,
            MediaStore.MediaColumns.MIME_TYPE,
            MediaStore.MediaColumns.RELATIVE_PATH,
            "datetaken",
            MediaStore.MediaColumns.DATE_MODIFIED,
        )
        val items = ArrayList<MediaItem>()
        context.contentResolver.query(
            collection, projection, null, null,
            "${MediaStore.MediaColumns.DATE_ADDED} ASC",
        )?.use { c ->
            while (c.moveToNext()) {
                if (!isSelected(c.getString(4), selected)) continue
                val id = c.getLong(0)
                val name = safeFileName(c.getString(1) ?: "$prefix$id")
                // The date in the file name (IMG_20250206_160717396.jpg) beats the file's own
                // timestamps, which turn into "the day it was copied" whenever a file is moved.
                val fromName = dateFromFileName(name)
                val taken = fromName ?: c.getLong(5).takeIf { it > 0 } ?: (c.getLong(6) * 1000)
                items += MediaItem(
                    key = "$prefix:$id",
                    uri = ContentUris.withAppendedId(collection, id),
                    name = name,
                    size = c.getLong(2),
                    mime = c.getString(3) ?: "application/octet-stream",
                    relativePath = c.getString(4),
                    takenAtMillis = taken,
                    fp = fingerprint(c.getLong(2), c.getLong(6)),
                    modifiedMillis = fromName ?: (c.getLong(6) * 1000),
                )
            }
        }
        return items
    }

    /** Every folder on the phone that holds photos or videos, with how many files each has. */
    fun discoverFolders(): List<Pair<String, Int>> {
        val counts = HashMap<String, Int>()
        for (uri in listOf(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, MediaStore.Video.Media.EXTERNAL_CONTENT_URI)) {
            context.contentResolver.query(uri, arrayOf(MediaStore.MediaColumns.RELATIVE_PATH), null, null, null)
                ?.use { c ->
                    while (c.moveToNext()) {
                        val folder = normalizePrefix(c.getString(0).orEmpty())
                        if (folder.isNotEmpty()) counts[folder] = (counts[folder] ?: 0) + 1
                    }
                }
        }
        return counts.entries.sortedBy { it.key.lowercase() }.map { it.key to it.value }
    }

    /** How many files in the chosen folders the app can see (0 with a permission problem). */
    fun visibleCount(): Int {
        val selected = settings.backupFolders
        return listOf(
            MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
            MediaStore.Video.Media.EXTERNAL_CONTENT_URI,
        ).sumOf { uri ->
            var n = 0
            context.contentResolver.query(uri, arrayOf(MediaStore.MediaColumns.RELATIVE_PATH), null, null, null)
                ?.use { c -> while (c.moveToNext()) if (isSelected(c.getString(0), selected)) n++ }
            n
        }
    }

    /** Every file in the chosen folders, whether or not it has been backed up. */
    fun scanAll(): List<MediaItem> {
        val selected = settings.backupFolders
        return query(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, "i", selected) +
            query(MediaStore.Video.Media.EXTERNAL_CONTENT_URI, "v", selected)
    }

    /** The files that still need uploading, given what the app remembers about each. */
    fun pending(all: List<MediaItem>, known: Map<String, BackupDb.Row>): List<MediaItem> =
        all.filter { item ->
            val row = known[item.key]
            // First time we see an already-uploaded file with no fingerprint: remember it as
            // the baseline, so an edit made from now on is noticed.
            if (row != null && row.status == "done" && row.fp == null) db.adoptFingerprint(item.key, item.fp)
            needsBackup(row?.status, row?.fp, item.fp)
        }

    private fun stopRequested() = LiveStatus.cancelRequested || shouldStop()

    /**
     * Backs up everything not yet backed up, [PARALLEL_UPLOADS] files at a time. A network or
     * login problem stops the run (and is rethrown); a problem with one file just marks that
     * file failed and carries on.
     */
    fun run(onProgress: (done: Int, total: Int, name: String) -> Unit = { _, _, _ -> }): BackupSummary {
        LiveStatus.start()
        log("scan: querying MediaStore for images and videos in ${settings.backupFolders.sorted()}")
        val known = db.allRows()
        val all: List<MediaItem>
        val items = try {
            all = scanAll()
            pending(all, known)
        } catch (e: Exception) {
            LiveStatus.finish()
            throw e
        }
        log("scan: ${items.size} file(s) still to back up")
        LiveStatus.total = items.size
        LiveStatus.bytesTotalAll = items.sumOf { it.size }
        items.forEach { LiveStatus.waiting.add(QueueEntry(it.name, it.size)) }
        LiveStatus.phase = "running"

        val queue = ConcurrentLinkedQueue(items)
        val fatal = AtomicReference<Exception?>(null)
        val pool = Executors.newFixedThreadPool(PARALLEL_UPLOADS)
        try {
            repeat(PARALLEL_UPLOADS) {
                pool.execute {
                    while (fatal.get() == null && !stopRequested()) {
                        val item = queue.poll() ?: break
                        LiveStatus.waiting.poll() // the oldest waiting entry is the one just taken
                        try {
                            process(item, items.size, onProgress)
                        } catch (e: Exception) {
                            fatal.compareAndSet(null, e)
                        }
                    }
                }
            }
        } finally {
            pool.shutdown()
            if (!pool.awaitTermination(24, TimeUnit.HOURS)) pool.shutdownNow()
        }
        fatal.get()?.let { throw it }
        if (!stopRequested()) syncDates(all, known)
        LiveStatus.finish()
        return BackupSummary(LiveStatus.done.get(), 0, LiveStatus.failed.get())
    }

    /** One file, start to finish. Throws only for problems that should stop the whole run. */
    private fun process(item: MediaItem, total: Int, onProgress: (Int, Int, String) -> Unit) {
        val active = ActiveItem(item.key, item.name, item.size)
        LiveStatus.active[item.key] = active
        val started = System.currentTimeMillis()
        log("file: ${item.name} (${item.size} bytes, ${item.mime}) key=${item.key}")
        try {
            val note = backUp(item, active)
            LiveStatus.done.incrementAndGet()
            LiveStatus.bytesDoneAll.addAndGet(item.size)
            val seconds = (System.currentTimeMillis() - started) / 1000.0
            log("  OK ${item.name} in ${System.currentTimeMillis() - started} ms ($note)")
            LiveStatus.addRecent(DoneEntry(item.name, item.size, true, "$note in ${"%.1f".format(seconds)}s"))
        } catch (e: ApiError) {
            if (e is AuthError || e.transient) {
                log("  STOP: ${e.javaClass.simpleName} ${e.message}")
                throw e
            }
            failFile(item, e.message ?: "the server refused it", "${e.javaClass.simpleName} ${e.message}")
        } catch (e: ApiUnavailable) {
            log("  STOP: server unreachable (${e.message})")
            throw e
        } catch (e: IOException) {
            // Unreadable or vanished file: record it, keep going.
            failFile(item, e.message ?: "could not read the file", "${e.javaClass.simpleName} ${e.message}")
        } catch (e: SecurityException) {
            throw e
        } catch (e: Exception) {
            failFile(item, "${e.javaClass.simpleName}: ${e.message}", "unexpected ${e.javaClass.simpleName} ${e.message}")
        } finally {
            LiveStatus.active.remove(item.key)
            onProgress(LiveStatus.done.get() + LiveStatus.failed.get(), total, item.name)
        }
    }

    /**
     * Puts the phone's own dates on files that were backed up before the server recorded them
     * (they all show the upload day otherwise). Runs after the uploads, a few at a time; a file
     * that fails is simply retried on the next run.
     */
    private fun syncDates(all: List<MediaItem>, known: Map<String, BackupDb.Row>) {
        val todo = all.filter { item ->
            val row = known[item.key]
            row != null && row.status == "done" && !row.datesDone && !row.remotePath.isNullOrEmpty()
        }
        if (todo.isEmpty()) return
        LiveStatus.phase = "dates"
        LiveStatus.datesTotal = todo.size
        log("dates: ${todo.size} backed-up file(s) need the phone's dates")
        val remote = try {
            api.snapshot()
        } catch (e: Exception) {
            log("dates: could not read the server's file list: ${e.javaClass.simpleName}: ${e.message}")
            return
        }
        val queue = ConcurrentLinkedQueue(todo)
        val stop = AtomicReference<String?>(null)
        val pool = Executors.newFixedThreadPool(PARALLEL_UPLOADS)
        repeat(PARALLEL_UPLOADS) {
            pool.execute {
                while (stop.get() == null && !stopRequested()) {
                    val item = queue.poll() ?: break
                    val row = known.getValue(item.key)
                    val id = remote[row.remotePath]?.id
                    try {
                        if (id == null) {
                            // The file is gone from the server (deleted or moved): nothing to fix.
                            db.markDates(item.key)
                        } else if (api.patchDates(id, isoFromMillis(item.takenAtMillis), isoFromMillis(item.modifiedMillis))) {
                            db.markDates(item.key)
                        } else {
                            stop.compareAndSet(null, "the server is too old to store dates: update it, then run again")
                        }
                        LiveStatus.datesDone.incrementAndGet()
                    } catch (e: ApiUnavailable) {
                        stop.compareAndSet(null, "server unreachable (${e.message})")
                    } catch (e: AuthError) {
                        stop.compareAndSet(null, "signed out")
                    } catch (e: Exception) {
                        log("dates: ${item.name} failed: ${e.javaClass.simpleName}: ${e.message}")
                        LiveStatus.datesDone.incrementAndGet()
                    }
                }
            }
        }
        pool.shutdown()
        if (!pool.awaitTermination(6, TimeUnit.HOURS)) pool.shutdownNow()
        val reason = stop.get()
        if (reason != null) log("dates: stopped, $reason") else log("dates: done, ${LiveStatus.datesDone.get()} file(s) updated")
    }

    private fun failFile(item: MediaItem, reason: String, logLine: String) {
        log("  FAILED ${item.name}: $logLine")
        db.set(item.key, "failed", error = reason)
        LiveStatus.failed.incrementAndGet()
        LiveStatus.bytesDoneAll.addAndGet(item.size)
        LiveStatus.addRecent(DoneEntry(item.name, item.size, false, reason))
    }

    private fun open(resolver: ContentResolver, uri: Uri) = {
        resolver.openInputStream(uri) ?: throw IOException("cannot open $uri")
    }

    @Synchronized
    private fun folderIdFor(folder: String): String =
        folderIds.getOrPut(folder) {
            log("  folder: ensure '$folder'")
            api.ensureFolder(folder)
        }

    /** Backs up one file; returns a short note on what happened. */
    private fun backUp(item: MediaItem, active: ActiveItem): String {
        val resolver = context.contentResolver
        val opener = open(resolver, item.uri)
        val folder = remoteFolderFor(settings.deviceName, item.relativePath)
        active.phase = "preparing"
        val folderId = folderIdFor(folder)
        val size = item.size.takeIf { it > 0 } ?: (resolver.openAssetFileDescriptor(item.uri, "r")?.use { it.length } ?: 0)
        val takenAt = isoFromMillis(item.takenAtMillis)
        val modifiedAt = isoFromMillis(item.modifiedMillis)
        var datesSent = modifiedAt != null
        val small = size <= CHUNKED_THRESHOLD

        // Small files are not hashed up front: the server hashes them anyway, and we only need
        // our own hash if the name turns out to be taken. That halves the reading for photos.
        var hash: String? = null
        fun ourHash(): String {
            hash?.let { return it }
            active.phase = "hashing"
            active.bytes = 0
            val start = System.currentTimeMillis()
            val computed = sha256Hex(opener) { active.bytes = it }
            log("  sha256 ${computed.take(12)}... of $size bytes in ${System.currentTimeMillis() - start} ms")
            hash = computed
            return computed
        }
        if (!small) ourHash() // large files are verified end to end by the server

        fun attempt(name: String): String? = try {
            active.phase = "uploading"
            active.bytes = 0
            log("  upload as '$folder/$name' (${if (small) "single request" else "chunked, resumable"})")
            api.uploadNew(
                opener, name, folderId, size, item.mime, hash.orEmpty(),
                resumeId = db.uploadId(item.key),
                onSession = { id ->
                    log("  upload session: ${id ?: "finished/cleared"}")
                    db.set(item.key, "uploading", uploadId = id)
                },
                onBytes = { active.bytes = it },
                takenAt = takenAt,
                modifiedAt = modifiedAt,
            )
            "$folder/$name"
        } catch (e: VersionConflict) {
            log("  name already taken on the server: '$name'")
            null
        }

        var note = "uploaded"
        var remote = attempt(item.name)
        if (remote == null) {
            // Name taken. Same bytes = already backed up (e.g. after a reinstall); different
            // bytes = keep both, as a conflict copy. Nothing is ever overwritten.
            val mine = ourHash()
            active.phase = "checking"
            val existing = api.snapshot()["$folder/${item.name}"]?.contentHash
            if (existing == mine) {
                log("  server already has identical bytes: counting as backed up")
                remote = "$folder/${item.name}"
                note = "already on the server"
                datesSent = false // the copy there may carry the upload day: the dates pass fixes it
            } else {
                val copy = conflictName(item.name, LocalDate.now().toString())
                log("  different bytes on the server: saving as conflict copy '$copy'")
                note = "saved as conflict copy"
                remote = attempt(copy)
                    ?: if (api.snapshot()["$folder/$copy"]?.contentHash == mine) "$folder/$copy"
                    else throw ApiError(409, "name clash for ${item.name}")
            }
        }
        db.set(item.key, "done", remotePath = remote, fp = item.fp, dates = datesSent)
        return note
    }
}
