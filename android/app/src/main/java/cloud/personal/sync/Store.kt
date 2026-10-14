package cloud.personal.sync

import android.content.ContentValues
import android.content.Context
import android.content.SharedPreferences
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/** Settings and tokens. Tokens live in EncryptedSharedPreferences (Android Keystore-backed). */
class Settings(context: Context) : TokenStore {
    private val prefs: SharedPreferences = EncryptedSharedPreferences.create(
        context,
        "secure_settings",
        MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    var serverUrl: String
        get() = prefs.getString("server_url", "") ?: ""
        set(v) = prefs.edit().putString("server_url", v).apply()
    var deviceName: String
        get() = prefs.getString("device_name", "") ?: ""
        set(v) = prefs.edit().putString("device_name", v).apply()
    override var access: String
        get() = prefs.getString("access", "") ?: ""
        set(v) = prefs.edit().putString("access", v).apply()
    override var refresh: String
        get() = prefs.getString("refresh", "") ?: ""
        set(v) = prefs.edit().putString("refresh", v).apply()
    var wifiOnly: Boolean
        get() = prefs.getBoolean("wifi_only", true)
        set(v) = prefs.edit().putBoolean("wifi_only", v).apply()
    var chargingOnly: Boolean
        get() = prefs.getBoolean("charging_only", true)
        set(v) = prefs.edit().putBoolean("charging_only", v).apply()
    var lastRun: String
        get() = prefs.getString("last_run", "never") ?: "never"
        set(v) = prefs.edit().putString("last_run", v).apply()
    var lastError: String
        get() = prefs.getString("last_error", "") ?: ""
        set(v) = prefs.edit().putString("last_error", v).apply()

    val loggedIn: Boolean get() = serverUrl.isNotEmpty() && refresh.isNotEmpty()

    fun logout() {
        access = ""
        refresh = ""
    }
}

/** Which media items are already backed up, plus resumable upload sessions. */
class BackupDb(context: Context) : SQLiteOpenHelper(context, "backup.db", null, 1) {
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            "CREATE TABLE media (key TEXT PRIMARY KEY, status TEXT NOT NULL, upload_id TEXT, " +
                "remote_path TEXT, error TEXT)"
        )
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {}

    fun status(key: String): String? =
        readableDatabase.rawQuery("SELECT status FROM media WHERE key=?", arrayOf(key)).use {
            if (it.moveToFirst()) it.getString(0) else null
        }

    fun uploadId(key: String): String? =
        readableDatabase.rawQuery("SELECT upload_id FROM media WHERE key=?", arrayOf(key)).use {
            if (it.moveToFirst()) it.getString(0) else null
        }

    fun set(
        key: String,
        status: String,
        uploadId: String? = null,
        remotePath: String? = null,
        error: String? = null,
    ) {
        val values = ContentValues().apply {
            put("key", key)
            put("status", status)
            put("upload_id", uploadId)
            put("remote_path", remotePath)
            put("error", error)
        }
        writableDatabase.insertWithOnConflict("media", null, values, SQLiteDatabase.CONFLICT_REPLACE)
    }

    /** Forget everything: a different server/account must get a full backup of its own. */
    fun clear() {
        writableDatabase.delete("media", null, null)
    }

    fun count(status: String): Int =
        readableDatabase.rawQuery("SELECT COUNT(*) FROM media WHERE status=?", arrayOf(status)).use {
            it.moveToFirst()
            it.getInt(0)
        }
}
