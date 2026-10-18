package cloud.personal.sync

import okhttp3.ConnectionPool
import okhttp3.Dispatcher
import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit

/**
 * The one HTTP client for the whole app. Every other client is a `newBuilder()` copy of it, so they all
 * share one connection pool and one dispatcher: a connection opened for the listing is reused for
 * thumbnails and viewer downloads instead of paying a fresh TCP (and TLS) handshake each time, which
 * over a 100-200 ms link is the single most expensive thing a request can do.
 */
object Net {
    val client: OkHttpClient = OkHttpClient.Builder()
        .connectionPool(ConnectionPool(16, 5, TimeUnit.MINUTES))
        .dispatcher(Dispatcher().apply { maxRequests = 64; maxRequestsPerHost = 16 })
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .build()

    /** For uploads and large downloads, which legitimately take minutes. */
    fun bulk(): OkHttpClient = client.newBuilder()
        .readTimeout(300, TimeUnit.SECONDS)
        .writeTimeout(300, TimeUnit.SECONDS)
        .build()
}
