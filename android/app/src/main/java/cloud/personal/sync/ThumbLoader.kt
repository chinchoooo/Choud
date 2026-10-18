package cloud.personal.sync

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.Handler
import android.os.Looper
import android.util.LruCache
import android.widget.ImageView
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.IOException
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/**
 * Loads thumbnails and images without a library: a small memory cache, a few worker threads,
 * and down-sampled decoding so a camera roll of thousands of photos stays light on memory.
 */
object ThumbLoader {
    private const val MAX_IMAGE_BYTES = 40L * 1024 * 1024

    private val cache = object : LruCache<String, Bitmap>(
        (Runtime.getRuntime().maxMemory() / 8).toInt().coerceAtMost(64 * 1024 * 1024),
    ) {
        override fun sizeOf(key: String, value: Bitmap) = value.byteCount
    }
    private val pool = Executors.newFixedThreadPool(4)
    private val main = Handler(Looper.getMainLooper())
    private val http = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .build()

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
        pool.execute {
            val bitmap = try {
                fetch(urlProvider(), targetPx)
            } catch (e: Exception) {
                null
            }
            if (bitmap != null) cache.put(key, bitmap)
            main.post {
                if (view.tag == key) {
                    if (bitmap != null) view.setImageBitmap(bitmap) else onFail()
                }
            }
        }
    }

    /** Blocking fetch + decode (call from a background thread). Null if it could not be decoded. */
    fun fetch(url: String, targetPx: Int): Bitmap? {
        val bytes = download(url) ?: return null
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null
        var sample = 1
        while (bounds.outWidth / (sample * 2) >= targetPx && bounds.outHeight / (sample * 2) >= targetPx) sample *= 2
        val options = BitmapFactory.Options().apply { inSampleSize = sample }
        return BitmapFactory.decodeByteArray(bytes, 0, bytes.size, options)
    }

    /** Decodes a local file (a copy kept offline) the same way `fetch` decodes a download. */
    fun fetchFile(file: java.io.File, targetPx: Int): Bitmap? {
        if (!file.isFile || file.length() > MAX_IMAGE_BYTES) return null
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(file.path, bounds)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null
        var sample = 1
        while (bounds.outWidth / (sample * 2) >= targetPx && bounds.outHeight / (sample * 2) >= targetPx) sample *= 2
        return BitmapFactory.decodeFile(file.path, BitmapFactory.Options().apply { inSampleSize = sample })
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

    fun clear() = cache.evictAll()
}
