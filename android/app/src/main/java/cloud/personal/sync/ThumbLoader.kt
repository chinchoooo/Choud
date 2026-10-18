package cloud.personal.sync

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.Handler
import android.os.Looper
import android.util.LruCache
import android.widget.ImageView
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.io.IOException
import java.lang.ref.WeakReference
import java.security.MessageDigest
import java.util.concurrent.LinkedBlockingDeque
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong

/**
 * Loads thumbnails and images without a library, tuned for a long photo grid over a slow link.
 *
 *  - **Visible first.** New requests go to the FRONT of the queue (a stack), so after a fast scroll the
 *    photos on screen load before the ones that scrolled past. A request whose view has since been
 *    reused for another photo is dropped without touching the network.
 *  - **Plenty in parallel.** Eight downloads at once, so a round-trip of 100 to 200 ms does not cap the
 *    grid at a few photos per second.
 *  - **Remembered.** Every thumbnail is kept on the phone (a 300 MB least-recently-used cache), so the
 *    second visit, and every launch after the first, shows photos instantly with no network at all.
 *  - **Read ahead.** `prefetch` warms the disk cache for photos just below the screen, at the BACK of
 *    the queue so it never delays what is being looked at.
 */
object ThumbLoader {
    private const val MAX_IMAGE_BYTES = 40L * 1024 * 1024
    private const val DISK_LIMIT_BYTES = 300L * 1024 * 1024
    private const val THREADS = 8

    private val cache = object : LruCache<String, Bitmap>(
        (Runtime.getRuntime().maxMemory() / 6).toInt().coerceAtMost(96 * 1024 * 1024),
    ) {
        override fun sizeOf(key: String, value: Bitmap) = value.byteCount
    }

    private class Job(val key: String, val view: WeakReference<ImageView>?, val targetPx: Int, val urlProvider: () -> String, val onFail: () -> Unit) : Runnable {
        override fun run() = runJob(this)
    }

    // A deque used as a stack for visible requests; read-ahead goes on the other end.
    private val queue = LinkedBlockingDeque<Runnable>()
    private val pool = ThreadPoolExecutor(THREADS, THREADS, 30, TimeUnit.SECONDS, queue).apply { allowCoreThreadTimeOut(true) }
    private val main = Handler(Looper.getMainLooper())
    private val http: OkHttpClient = Net.client

    @Volatile private var diskDir: File? = null
    private val lastTrim = AtomicLong(0)

    /** Call once at startup so thumbnails can be kept on disk. */
    fun init(context: Context) {
        if (diskDir != null) return
        diskDir = File(context.applicationContext.cacheDir, "thumbs").apply { mkdirs() }
        pool.execute { trimDisk() }
    }

    private fun diskFile(key: String): File? {
        val dir = diskDir ?: return null
        val digest = MessageDigest.getInstance("SHA-1").digest(key.toByteArray())
        return File(dir, digest.joinToString("") { "%02x".format(it) })
    }

    private fun trimDisk() {
        val dir = diskDir ?: return
        val now = System.currentTimeMillis()
        if (now - lastTrim.get() < 60_000) return
        lastTrim.set(now)
        val files = dir.listFiles()?.filter { it.isFile } ?: return
        var total = files.sumOf { it.length() }
        if (total <= DISK_LIMIT_BYTES) return
        for (file in files.sortedBy { it.lastModified() }) {
            if (total <= DISK_LIMIT_BYTES * 8 / 10) break
            total -= file.length()
            file.delete()
        }
    }

    /**
     * Shows the image for `key` in `view` when it arrives. `urlProvider` runs on a worker thread
     * (it may need to fetch a media token). `onFail` runs if there is no thumbnail for the file.
     */
    fun load(view: ImageView, key: String, targetPx: Int, urlProvider: () -> String, onFail: () -> Unit = {}) {
        view.tag = key
        cache.get(key)?.let {
            view.setImageBitmap(it)
            return
        }
        view.setImageDrawable(null)
        // To the FRONT: what was just bound is what is on screen now.
        queue.offerFirst(Job(key, WeakReference(view), targetPx, urlProvider, onFail))
        pool.prestartAllCoreThreads()
    }

    /** Warms the disk cache for photos that are about to scroll into view (no view is involved). */
    fun prefetch(key: String, targetPx: Int, urlProvider: () -> String) {
        val file = diskFile(key)
        if (cache.get(key) != null || (file != null && file.exists())) return
        queue.offerLast(Job(key, null, targetPx, urlProvider) {})
        pool.prestartAllCoreThreads()
    }

    /** Fetches (in batches) every thumbnail in `items` that is not on disk yet. Returns how many arrived. Blocking. */
    fun warm(api: ApiClient, items: List<RemoteItem>, px: Int = 256): Int {
        var got = 0
        val wanted = items.filter { !it.isLocalOnly }.filter { item ->
            val file = diskFile("w:${item.id}:${item.version}:$px")
            file == null || !file.exists()
        }
        for (group in wanted.chunked(BATCH_SIZE)) {
            val frames = try {
                api.thumbBatch(group.map { it.id }, px)
            } catch (e: Exception) {
                break
            }
            val byId = group.associateBy { it.id }
            for (frame in frames) {
                if (frame.status != 0) continue
                val item = byId[frame.id] ?: continue
                val target = diskFile("w:${item.id}:${item.version}:$px") ?: continue
                try {
                    val part = File(target.parentFile, target.name + ".part")
                    part.writeBytes(frame.bytes)
                    if (!part.renameTo(target)) part.delete() else got++
                } catch (_: IOException) {
                }
            }
        }
        if (got > 0) trimDisk()
        return got
    }

    /** Thumbnails of photos that are only on the phone: read from the phone, never from the network. */
    fun loadLocal(view: ImageView, context: Context, uri: String, px: Int = 256) {
        val key = "l:$uri:$px"
        view.tag = key
        cache.get(key)?.let {
            view.setImageBitmap(it)
            return
        }
        view.setImageDrawable(null)
        queue.offerFirst(
            Runnable {
                if (view.tag != key) return@Runnable
                val bitmap = try {
                    val parsed = android.net.Uri.parse(uri)
                    if (android.os.Build.VERSION.SDK_INT >= 29) {
                        context.contentResolver.loadThumbnail(parsed, android.util.Size(px, px), null)
                    } else {
                        context.contentResolver.openInputStream(parsed)?.use { decodeStreamSampled(it, px) }
                    }
                } catch (e: Exception) {
                    null
                } ?: return@Runnable
                cache.put(key, bitmap)
                main.post { if (view.tag == key) view.setImageBitmap(bitmap) }
            },
        )
        pool.prestartAllCoreThreads()
    }

    private fun decodeStreamSampled(stream: java.io.InputStream, px: Int): Bitmap? {
        val bytes = stream.readBytes()
        return decodeBytes(bytes, px)
    }

    /** A screen-sized bitmap of a phone photo (for the viewer). */
    fun fetchLocal(context: Context, uri: String, maxPx: Int): Bitmap? = try {
        context.contentResolver.openInputStream(android.net.Uri.parse(uri))?.use { decodeStreamSampled(it, maxPx) }
    } catch (e: Exception) {
        null
    }

    // ------------------------------------------------------------------------------------------
    // Photos: placeholder at once, thumbnails fetched a screenful at a time in ONE request.

    private class PhotoJob(val key: String, val id: String, val version: String, val view: WeakReference<ImageView>?, val px: Int)

    private val pending = ArrayList<PhotoJob>()
    private var flushPosted = false
    private val flush = Runnable { flushPending() }
    private const val BATCH_SIZE = 24

    /**
     * Shows a photo's thumbnail in `view`. The blurry stand-in (`placeholder`, a ThumbHash) is drawn
     * immediately; the real picture follows from memory, disk, or one batched request for everything
     * that is on screen at the same moment. Must be called on the main thread.
     */
    fun loadPhoto(view: ImageView, api: ApiClient, id: String, version: String, placeholder: String, px: Int = 256) {
        val key = "w:$id:$version:$px"
        view.tag = key
        cache.get(key)?.let {
            view.setImageBitmap(it)
            return
        }
        val blur = if (placeholder.isNotEmpty()) ThumbHash.bitmap(placeholder) else null
        if (blur != null) view.setImageBitmap(blur) else view.setImageDrawable(null)
        pending.add(PhotoJob(key, id, version, WeakReference(view), px))
        schedule(api)
    }

    /** Warms the disk cache for photos about to scroll into view. Main thread. */
    fun prefetchPhoto(api: ApiClient, id: String, version: String, px: Int = 256) {
        val key = "w:$id:$version:$px"
        val file = diskFile(key)
        if (cache.get(key) != null || (file != null && file.exists())) return
        if (pending.any { it.key == key }) return
        pending.add(PhotoJob(key, id, version, null, px))
        schedule(api)
    }

    @Volatile private var batchApi: ApiClient? = null

    private fun schedule(api: ApiClient) {
        batchApi = api
        if (!flushPosted) {
            flushPosted = true
            // One frame is enough to gather everything a fast scroll just bound.
            main.postDelayed(flush, 12)
        }
    }

    private fun flushPending() {
        flushPosted = false
        val api = batchApi ?: return
        val jobs = ArrayList(pending)
        pending.clear()
        // What was bound last is what is on screen now: newest first, read-ahead last.
        val visible = jobs.filter { it.view != null }.reversed()
        val ahead = jobs.filter { it.view == null }
        for (group in (visible + ahead).chunked(BATCH_SIZE)) {
            val runnable = Runnable { runPhotoGroup(api, group) }
            if (group.first().view != null) queue.offerFirst(runnable) else queue.offerLast(runnable)
        }
        pool.prestartAllCoreThreads()
    }

    private fun stillWanted(job: PhotoJob): Boolean {
        val view = job.view ?: return true
        val target = view.get() ?: return false
        return target.tag == job.key
    }

    private fun show(job: PhotoJob, bitmap: Bitmap) {
        if (job.view == null) return
        main.post {
            val target = job.view.get() ?: return@post
            if (target.tag == job.key) target.setImageBitmap(bitmap)
        }
    }

    private fun runPhotoGroup(api: ApiClient, group: List<PhotoJob>) {
        val misses = ArrayList<PhotoJob>()
        for (job in group) {
            if (!stillWanted(job)) continue
            val inMemory = cache.get(job.key)
            if (inMemory != null) {
                show(job, inMemory)
                continue
            }
            val file = diskFile(job.key)?.takeIf { it.isFile && it.length() > 0 }
            if (file != null) {
                file.setLastModified(System.currentTimeMillis())
                val bitmap = decodeFile(file, job.px)
                if (bitmap != null) {
                    cache.put(job.key, bitmap)
                    show(job, bitmap)
                    continue
                }
            }
            misses.add(job)
        }
        if (misses.isEmpty()) return
        // Several jobs can want the same photo (a visible cell and a read-ahead): all get the answer.
        val byId = HashMap<String, MutableList<PhotoJob>>()
        misses.forEach { byId.getOrPut(it.id) { ArrayList() }.add(it) }
        val frames = try {
            api.thumbBatch(byId.keys.toList(), misses.first().px)
        } catch (e: Exception) {
            EventLog.log("thumbnails: batch failed: ${e.javaClass.simpleName}: ${e.message}")
            return
        }
        val answered = HashSet<String>()
        for (frame in frames) {
            val jobs = byId[frame.id] ?: continue
            answered.add(frame.id)
            when (frame.status) {
                0 -> keepAndShow(jobs, frame.bytes)
                1 -> fetchOne(api, jobs) // the server had not made it yet: ask on its own
                else -> {} // no thumbnail for this file: the placeholder stays
            }
        }
        // A cut-off answer: whatever never arrived is fetched singly.
        byId.filterKeys { it !in answered }.values.forEach { fetchOne(api, it) }
    }

    private fun fetchOne(api: ApiClient, jobs: List<PhotoJob>) {
        val job = jobs.firstOrNull { stillWanted(it) } ?: return
        val bytes = try {
            api.thumbFetch(job.id, job.px, job.version)
        } catch (e: Exception) {
            null
        } ?: return
        keepAndShow(jobs, bytes)
    }

    private fun keepAndShow(jobs: List<PhotoJob>, bytes: ByteArray) {
        val job = jobs.first()
        diskFile(job.key)?.let { target ->
            try {
                val part = File(target.parentFile, target.name + ".part")
                part.writeBytes(bytes)
                if (!part.renameTo(target)) part.delete()
            } catch (_: IOException) {
                // the disk cache is a bonus: failing to write it must never fail the image
            }
            if (lastTrim.get() + 60_000 < System.currentTimeMillis()) trimDisk()
        }
        val bitmap = decodeBytes(bytes, job.px) ?: return
        cache.put(job.key, bitmap)
        jobs.forEach { show(it, bitmap) }
    }

    private fun runJob(job: Job) {
        val view = job.view?.get()
        if (job.view != null && (view == null || view.tag != job.key)) return // scrolled away: skip
        val bitmap = try {
            decodeFromDisk(job) ?: downloadAndKeep(job)
        } catch (e: Exception) {
            null
        }
        if (bitmap != null) cache.put(job.key, bitmap)
        if (job.view == null) return // read-ahead: the disk file is the point
        main.post {
            val target = job.view.get() ?: return@post
            if (target.tag == job.key) {
                if (bitmap != null) target.setImageBitmap(bitmap) else job.onFail()
            }
        }
    }

    private fun decodeFromDisk(job: Job): Bitmap? {
        val file = diskFile(job.key)?.takeIf { it.isFile && it.length() > 0 } ?: return null
        file.setLastModified(System.currentTimeMillis()) // keep recently used ones
        return decodeFile(file, job.targetPx)
    }

    private fun downloadAndKeep(job: Job): Bitmap? {
        val bytes = download(job.urlProvider()) ?: return null
        diskFile(job.key)?.let { target ->
            try {
                val part = File(target.parentFile, target.name + ".part")
                part.writeBytes(bytes)
                if (!part.renameTo(target)) part.delete()
            } catch (_: IOException) {
                // the disk cache is a bonus: failing to write it must never fail the image
            }
            if (lastTrim.get() + 60_000 < System.currentTimeMillis()) trimDisk()
        }
        return decodeBytes(bytes, job.targetPx)
    }

    /** Blocking fetch + decode (call from a background thread). Null if it could not be decoded. */
    fun fetch(url: String, targetPx: Int): Bitmap? {
        val bytes = download(url) ?: return null
        return decodeBytes(bytes, targetPx)
    }

    private fun sampleFor(width: Int, height: Int, targetPx: Int): Int {
        var sample = 1
        while (width / (sample * 2) >= targetPx && height / (sample * 2) >= targetPx) sample *= 2
        return sample
    }

    private fun decodeBytes(bytes: ByteArray, targetPx: Int): Bitmap? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null
        val options = BitmapFactory.Options().apply { inSampleSize = sampleFor(bounds.outWidth, bounds.outHeight, targetPx) }
        return BitmapFactory.decodeByteArray(bytes, 0, bytes.size, options)
    }

    private fun decodeFile(file: File, targetPx: Int): Bitmap? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(file.path, bounds)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) {
            file.delete() // a damaged cache entry: forget it and fetch again
            return null
        }
        val options = BitmapFactory.Options().apply { inSampleSize = sampleFor(bounds.outWidth, bounds.outHeight, targetPx) }
        return BitmapFactory.decodeFile(file.path, options)
    }

    /** Decodes a local file (a copy kept offline) the same way `fetch` decodes a download. */
    fun fetchFile(file: File, targetPx: Int): Bitmap? {
        if (!file.isFile || file.length() > MAX_IMAGE_BYTES) return null
        return decodeFile(file, targetPx)
    }

    private fun download(url: String): ByteArray? {
        val request = Request.Builder().url(url).build()
        http.newCall(request).execute().use { response ->
            if (!response.isSuccessful) return null
            val body = response.body ?: return null
            if (body.contentLength() > MAX_IMAGE_BYTES) return null
            return try {
                body.bytes()
            } catch (e: IOException) {
                null
            }
        }
    }

    fun clear() {
        cache.evictAll()
        diskDir?.listFiles()?.forEach { it.delete() }
    }
}
