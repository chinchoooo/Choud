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
    private val http = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .connectionPool(okhttp3.ConnectionPool(THREADS, 5, TimeUnit.MINUTES))
        .build()

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
