package cloud.personal.sync

import android.content.ContentValues
import android.content.Context
import android.content.SharedPreferences
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/**
 * Settings and tokens. Everything that is not a secret lives in ordinary preferences, which open in
 * a millisecond. Only the two login tokens live in EncryptedSharedPreferences (Android Keystore), and
 * that store is opened lazily, off the start-up path, the first time a token is actually needed.
 */
class Settings(private val context: Context) : TokenStore {
    private val plain: SharedPreferences = context.getSharedPreferences("choud_plain", Context.MODE_PRIVATE)

    private val secure: SharedPreferences by lazy {
        EncryptedSharedPreferences.create(
            context,
            "secure_settings",
            MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    init {
        migrateOnce()
    }

    /** One time, after an update from a version that kept everything encrypted: copy the plain values out. */
    private fun migrateOnce() {
        if (plain.getBoolean("migrated", false)) return
        val old = secure
        val edit = plain.edit()
        for (key in listOf("server_url", "alt_server_url", "device_name", "wifi_only", "charging_only", "backup_folders", "theme", "last_run", "last_error", "photo_columns", "keep_fresh")) {
            when (val value = old.all[key]) {
                is String -> edit.putString(key, value)
                is Boolean -> edit.putBoolean(key, value)
                is Int -> edit.putInt(key, value)
            }
        }
        edit.putBoolean("logged_in", !old.getString("refresh", "").isNullOrEmpty())
        edit.putBoolean("migrated", true).apply()
    }

    private val prefs: SharedPreferences get() = plain

    var serverUrl: String
        get() = prefs.getString("server_url", "") ?: ""
        set(v) = prefs.edit().putString("server_url", v).apply()
    /** An optional second address (a public one) used when the private one does not answer. */
    var altServerUrl: String
        get() = prefs.getString("alt_server_url", "") ?: ""
        set(v) = prefs.edit().putString("alt_server_url", v).apply()

    /** Whether to refresh the library and its thumbnails daily while charging on Wi-Fi. */
    var keepFresh: Boolean
        get() = prefs.getBoolean("keep_fresh", true)
        set(value) = prefs.edit().putBoolean("keep_fresh", value).apply()

    /** How many photos fit across the grid (pinch to change). */
    var photoColumns: Int
        get() = prefs.getInt("photo_columns", 3)
        set(value) = prefs.edit().putInt("photo_columns", value).apply()

    /** The address that answered most recently (private first, then the public one); not saved. */
    @Volatile
    var activeUrl: String = ""

    /** What to talk to right now. */
    val baseUrl: String get() = activeUrl.ifEmpty { serverUrl }

    var deviceName: String
        get() = prefs.getString("device_name", "") ?: ""
        set(v) = prefs.edit().putString("device_name", v).apply()
    override var access: String
        get() = secure.getString("access", "") ?: ""
        set(v) = secure.edit().putString("access", v).apply()
    override var refresh: String
        get() = secure.getString("refresh", "") ?: ""
        set(v) {
            secure.edit().putString("refresh", v).apply()
            plain.edit().putBoolean("logged_in", v.isNotEmpty()).apply()
        }
    var wifiOnly: Boolean
        get() = prefs.getBoolean("wifi_only", true)
        set(v) = prefs.edit().putBoolean("wifi_only", v).apply()
    var chargingOnly: Boolean
        get() = prefs.getBoolean("charging_only", true)
        set(v) = prefs.edit().putBoolean("charging_only", v).apply()
    /** Folders (MediaStore relative paths, normalised with a trailing slash) to back up. */
    var backupFolders: Set<String>
        get() {
            val raw = prefs.getString("backup_folders", null) ?: return DEFAULT_BACKUP_PREFIXES
            return raw.split('\n').map { normalizePrefix(it) }.filter { it.isNotEmpty() }.toSet()
        }
        set(v) = prefs.edit().putString("backup_folders", v.sorted().joinToString("\n")).apply()
    var theme: String
        get() = prefs.getString("theme", "retro") ?: "retro"
        set(v) = prefs.edit().putString("theme", v).apply()
    var lastRun: String
        get() = prefs.getString("last_run", "never") ?: "never"
        set(v) = prefs.edit().putString("last_run", v).apply()
    var lastError: String
        get() = prefs.getString("last_error", "") ?: ""
        set(v) = prefs.edit().putString("last_error", v).apply()

    val loggedIn: Boolean get() = serverUrl.isNotEmpty() && plain.getBoolean("logged_in", false)

    fun logout() {
        access = ""
        refresh = ""
    }
}

/** Which media items are already backed up, plus resumable upload sessions. */
class BackupDb(context: Context) : SQLiteOpenHelper(context, "backup.db", null, 3) {
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            "CREATE TABLE media (key TEXT PRIMARY KEY, status TEXT NOT NULL, upload_id TEXT, " +
                "remote_path TEXT, error TEXT, fp TEXT, dates INTEGER)"
        )
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        if (oldVersion < 2) db.execSQL("ALTER TABLE media ADD COLUMN fp TEXT")
        // dates: 1 once the phone's own dates are on the server; NULL = still to do
        if (oldVersion < 3) db.execSQL("ALTER TABLE media ADD COLUMN dates INTEGER")
    }

    /** Records a fingerprint for a file uploaded before fingerprints existed, so later edits show. */
    fun adoptFingerprint(key: String, fp: String) {
        writableDatabase.execSQL(
            "UPDATE media SET fp = ? WHERE key = ? AND status = 'done' AND fp IS NULL",
            arrayOf(fp, key),
        )
    }

    /** Everything the app remembers about one file. */
    data class Row(val status: String, val fp: String?, val datesDone: Boolean, val remotePath: String?)

    fun allRows(): Map<String, Row> =
        readableDatabase.rawQuery("SELECT key, status, fp, dates, remote_path FROM media", null).use { c ->
            val map = HashMap<String, Row>()
            while (c.moveToNext()) {
                map[c.getString(0)] = Row(c.getString(1), c.getString(2), !c.isNull(3), c.getString(4))
            }
            map
        }

    fun markDates(key: String) {
        writableDatabase.execSQL("UPDATE media SET dates = 1 WHERE key = ?", arrayOf(key))
    }

    /** Backed-up files whose phone dates have not been sent to the server yet. */
    fun countDatesPending(): Int =
        readableDatabase.rawQuery("SELECT COUNT(*) FROM media WHERE status='done' AND dates IS NULL AND remote_path IS NOT NULL", null).use {
            it.moveToFirst()
            it.getInt(0)
        }

    /** status and stored fingerprint of every known file, read once per scan. */
    fun allStatuses(): Map<String, Pair<String, String?>> =
        readableDatabase.rawQuery("SELECT key, status, fp FROM media", null).use { c ->
            val map = HashMap<String, Pair<String, String?>>()
            while (c.moveToNext()) map[c.getString(0)] = c.getString(1) to c.getString(2)
            map
        }

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
        fp: String? = null,
        dates: Boolean = false,
    ) {
        val values = ContentValues().apply {
            put("fp", fp)
            if (dates) put("dates", 1) else putNull("dates")
            put("key", key)
            put("status", status)
            put("upload_id", uploadId)
            put("remote_path", remotePath)
            put("error", error)
        }
        writableDatabase.insertWithOnConflict("media", null, values, SQLiteDatabase.CONFLICT_REPLACE)
    }

    /** The most recent failures, newest first, as "key: error". */
    fun failures(limit: Int = 5): List<String> =
        readableDatabase.rawQuery(
            "SELECT key, error FROM media WHERE status='failed' ORDER BY rowid DESC LIMIT ?",
            arrayOf(limit.toString()),
        ).use { c ->
            val out = ArrayList<String>()
            while (c.moveToNext()) out += "${c.getString(0)}: ${c.getString(1)}"
            out
        }

    /** Puts failed files back in the queue so the next run tries them again. */
    fun resetFailed(): Int =
        writableDatabase.delete("media", "status = ?", arrayOf("failed"))

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
