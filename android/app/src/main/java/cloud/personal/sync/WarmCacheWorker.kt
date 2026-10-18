package cloud.personal.sync

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.util.concurrent.TimeUnit

/**
 * Once a day, on Wi-Fi and while charging, brings the phone's copy of the library up to date and
 * downloads the thumbnails of the newest photos. Opening Photos later, anywhere and even without a
 * connection, then shows pictures at once instead of waiting on the network. Costs a few MB.
 */
class WarmCacheWorker(private val context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        EventLog.init(context)
        ThumbLoader.init(context)
        val settings = Settings(context)
        if (!settings.loggedIn || !settings.keepFresh) return@withContext Result.success()
        try {
            val api = ApiClient(ServerPicker.pick(settings), settings, log = EventLog::log)
            val db = LibraryDb(context)
            try {
                Library.sync(db, api)
                val newest = db.load("all").take(WARM_COUNT)
                val warmed = ThumbLoader.warm(api, newest)
                EventLog.log("warm cache: ${warmed} thumbnail(s) fetched for the newest ${newest.size} photos")
            } finally {
                db.close()
            }
            Result.success()
        } catch (e: ApiUnavailable) {
            Result.retry()
        } catch (e: Exception) {
            EventLog.log("warm cache failed: ${e.javaClass.simpleName}: ${e.message}")
            Result.success() // a nice-to-have: never retry hard
        }
    }

    companion object {
        private const val NAME = "warm-cache"
        private const val WARM_COUNT = 600

        fun schedule(context: Context, settings: Settings) {
            val manager = WorkManager.getInstance(context)
            if (!settings.keepFresh) {
                manager.cancelUniqueWork(NAME)
                return
            }
            val request = PeriodicWorkRequestBuilder<WarmCacheWorker>(1, TimeUnit.DAYS)
                .setConstraints(
                    Constraints.Builder()
                        .setRequiredNetworkType(NetworkType.UNMETERED)
                        .setRequiresCharging(true)
                        .build(),
                )
                .build()
            manager.enqueueUniquePeriodicWork(NAME, ExistingPeriodicWorkPolicy.UPDATE, request)
        }
    }
}
