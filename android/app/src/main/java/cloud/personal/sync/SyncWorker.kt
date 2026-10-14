package cloud.personal.sync

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.pm.ServiceInfo
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.ForegroundInfo
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.time.LocalDateTime
import java.util.concurrent.TimeUnit

class SyncWorker(private val context: Context, params: WorkerParameters) :
    CoroutineWorker(context, params) {

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val settings = Settings(context)
        settings.lastRun = "started " + LocalDateTime.now().withNano(0).toString().replace('T', ' ')
        if (!settings.loggedIn) return@withContext Result.success()
        val db = BackupDb(context)
        try {
            runCatching { setForeground(foregroundInfo("Backing up photos…")) }
            val api = ApiClient(settings.serverUrl, settings)
            val summary = CameraBackup(context, settings, db, api).run { done, total, name ->
                runCatching { setForegroundAsync(foregroundInfo("Backing up $name (${done + 1}/$total)")) }
            }
            settings.lastRun = LocalDateTime.now().withNano(0).toString().replace('T', ' ') +
                " - ${summary.uploaded} uploaded, ${summary.failed} failed"
            settings.lastError = ""
            Result.success()
        } catch (e: ApiUnavailable) {
            settings.lastError = "Server unreachable; will retry"
            Result.retry()
        } catch (e: AuthError) {
            settings.lastError = "Signed out: log in again"
            Result.failure()
        } catch (e: ApiError) {
            settings.lastError = e.message ?: "server error"
            if (e.transient) Result.retry() else Result.failure()
        } catch (e: SecurityException) {
            settings.lastError = "No permission to read photos: allow Photos and videos (All) in the app's permissions"
            Result.failure()
        } catch (e: Exception) {
            settings.lastError = "${e.javaClass.simpleName}: ${e.message}"
            Result.failure()
        } finally {
            db.close()
        }
    }

    private fun foregroundInfo(text: String): ForegroundInfo {
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= 26) {
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL, "Backup", NotificationManager.IMPORTANCE_LOW)
            )
        }
        val notification = NotificationCompat.Builder(context, CHANNEL)
            .setContentTitle("Personal Cloud")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.stat_sys_upload)
            .setOngoing(true)
            .build()
        return if (Build.VERSION.SDK_INT >= 29) {
            ForegroundInfo(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            ForegroundInfo(NOTIFICATION_ID, notification)
        }
    }

    companion object {
        private const val CHANNEL = "backup"
        private const val NOTIFICATION_ID = 1
        private const val PERIODIC = "camera-backup-periodic"
        private const val ONCE = "camera-backup-now"

        private fun constraints(settings: Settings) = Constraints.Builder()
            .setRequiredNetworkType(if (settings.wifiOnly) NetworkType.UNMETERED else NetworkType.CONNECTED)
            .setRequiresCharging(settings.chargingOnly)
            .build()

        /** (Re)schedule the periodic backup with the user's current constraints. */
        fun schedule(context: Context, settings: Settings) {
            val request = PeriodicWorkRequestBuilder<SyncWorker>(1, TimeUnit.HOURS)
                .setConstraints(constraints(settings))
                .setBackoffCriteria(androidx.work.BackoffPolicy.EXPONENTIAL, 5, TimeUnit.MINUTES)
                .build()
            WorkManager.getInstance(context)
                .enqueueUniquePeriodicWork(PERIODIC, ExistingPeriodicWorkPolicy.UPDATE, request)
        }

        /** "Sync now" replaces any stuck/backing-off earlier attempt. Ignores the charging/Wi-Fi constraints, needs only a connection. */
        fun runNow(context: Context) {
            val request = OneTimeWorkRequestBuilder<SyncWorker>()
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            WorkManager.getInstance(context).enqueueUniqueWork(ONCE, ExistingWorkPolicy.REPLACE, request)
        }

        fun cancel(context: Context) {
            WorkManager.getInstance(context).cancelUniqueWork(PERIODIC)
            WorkManager.getInstance(context).cancelUniqueWork(ONCE)
        }
    }
}
