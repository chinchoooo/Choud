package cloud.personal.sync

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper

/**
 * The photo library kept on the phone: one row per photo or video the server has, with its blurry
 * placeholder. Photos reads it directly, so any month is on screen at once with no network, and a
 * refresh only has to fetch what changed since the last one (a few rows, or a bodyless 304).
 */
class LibraryDb(context: Context) : SQLiteOpenHelper(context.applicationContext, "library.db", null, 1) {
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            """CREATE TABLE photo(
                id TEXT PRIMARY KEY, name TEXT NOT NULL, mime TEXT NOT NULL, size INTEGER NOT NULL,
                taken INTEGER, modified INTEGER, created INTEGER, hash TEXT NOT NULL,
                thumbhash TEXT NOT NULL, folder TEXT NOT NULL, fav INTEGER NOT NULL DEFAULT 0,
                sort INTEGER NOT NULL, video INTEGER NOT NULL DEFAULT 0)""",
        )
        db.execSQL("CREATE INDEX photo_sort ON photo(sort DESC)")
        db.execSQL("CREATE TABLE kv(k TEXT PRIMARY KEY, v TEXT NOT NULL)")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        db.execSQL("DROP TABLE IF EXISTS photo")
        db.execSQL("DROP TABLE IF EXISTS kv")
        onCreate(db)
    }

    fun get(key: String): String? =
        readableDatabase.rawQuery("SELECT v FROM kv WHERE k=?", arrayOf(key)).use { if (it.moveToFirst()) it.getString(0) else null }

    private fun set(db: SQLiteDatabase, key: String, value: String?) {
        if (value == null) db.delete("kv", "k=?", arrayOf(key))
        else db.insertWithOnConflict("kv", null, ContentValues().apply { put("k", key); put("v", value) }, SQLiteDatabase.CONFLICT_REPLACE)
    }

    /** Applies an index answer in one transaction: upsert rows, delete removed ids, reset the stars. */
    fun apply(result: LibraryIndexResult) {
        val db = writableDatabase
        db.beginTransaction()
        try {
            if (result.full) db.delete("photo", null, null)
            for (r in result.rows) {
                val sort = r.taken ?: r.modified ?: r.created ?: 0L
                db.insertWithOnConflict(
                    "photo", null,
                    ContentValues().apply {
                        put("id", r.id); put("name", r.name); put("mime", r.mime); put("size", r.size)
                        put("taken", r.taken); put("modified", r.modified); put("created", r.created)
                        put("hash", r.hash); put("thumbhash", r.thumbhash); put("folder", r.folderPath)
                        put("sort", sort); put("video", if (r.mime.startsWith("video/")) 1 else 0)
                        put("fav", 0)
                    },
                    SQLiteDatabase.CONFLICT_REPLACE,
                )
            }
            for (id in result.removed) db.delete("photo", "id=?", arrayOf(id))
            db.execSQL("UPDATE photo SET fav=0")
            for (id in result.favorites) db.execSQL("UPDATE photo SET fav=1 WHERE id=?", arrayOf(id))
            set(db, "cursor", result.cursor)
            set(db, "etag", result.etag)
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
    }

    fun cursor(): String? = get("cursor")
    fun etag(): String? = get("etag")

    fun setFavorite(ids: Collection<String>, on: Boolean) {
        val db = writableDatabase
        db.beginTransaction()
        try {
            for (id in ids) db.execSQL("UPDATE photo SET fav=? WHERE id=?", arrayOf(if (on) 1 else 0, id))
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
    }

    fun remove(ids: Collection<String>) {
        val db = writableDatabase
        db.beginTransaction()
        try {
            for (id in ids) db.delete("photo", "id=?", arrayOf(id))
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
    }

    /** Newest first. `kind` is "all", "image" or "video". */
    fun load(kind: String): List<RemoteItem> {
        val where = when (kind) {
            "image" -> "WHERE video=0"
            "video" -> "WHERE video=1"
            else -> ""
        }
        val out = ArrayList<RemoteItem>()
        readableDatabase.rawQuery(
            "SELECT id,name,mime,size,taken,modified,created,hash,thumbhash,folder,fav FROM photo $where ORDER BY sort DESC, id",
            null,
        ).use { c ->
            while (c.moveToNext()) {
                out.add(
                    RemoteItem(
                        id = c.getString(0), name = c.getString(1), mime = c.getString(2), size = c.getLong(3),
                        favorite = c.getInt(10) == 1, folderPath = c.getString(9),
                        takenAtMillis = if (c.isNull(4)) null else c.getLong(4),
                        createdAtMillis = if (c.isNull(6)) null else c.getLong(6),
                        modifiedAtMillis = if (c.isNull(5)) null else c.getLong(5),
                        thumbhash = c.getString(8), version = c.getString(7).take(12),
                    ),
                )
            }
        }
        return out
    }

    fun clear() {
        val db = writableDatabase
        db.delete("photo", null, null)
        db.delete("kv", null, null)
    }
}

/** Brings the local library up to date with the server (delta if possible) and reports if anything changed. */
object Library {
    @Synchronized
    fun sync(db: LibraryDb, api: ApiClient): Boolean {
        val cursor = db.cursor()
        // A delta needs the cursor; the ETag only matches the exact question that produced it.
        val result = api.libraryIndex(cursor, db.etag()) ?: return false
        db.apply(result)
        return true
    }
}
