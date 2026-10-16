package cloud.personal.sync

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.pdf.PdfRenderer
import android.net.Uri
import android.os.Bundle
import android.os.ParcelFileDescriptor
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.MediaController
import android.widget.ScrollView
import android.widget.TextView
import android.widget.VideoView
import androidx.core.content.FileProvider
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import java.io.File
import java.util.concurrent.Executors
import kotlin.concurrent.thread

/**
 * The app's own viewer. Images (pinch/drag/double-tap), video and audio (streamed, seekable),
 * PDF and text/code are all shown in here; another app is only offered for formats the app
 * does not know, or on request via "Open with".
 */
class ViewerActivity : Activity() {
    private lateinit var ui: Ui
    private lateinit var settings: Settings
    private lateinit var api: ApiClient
    private lateinit var items: MutableList<RemoteItem>
    private var index = 0

    private lateinit var title: TextView
    private lateinit var subtitle: TextView
    private lateinit var star: TextView
    private lateinit var stage: FrameLayout
    private lateinit var prevButton: View
    private lateinit var nextButton: View

    /** Bumped on every navigation so a slow load for a previous file never paints over the new one. */
    @Volatile private var generation = 0
    private var video: VideoView? = null
    private var zoom: ZoomImageView? = null
    private var pdf: PdfSession? = null
    private var swipeStartX = 0f

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        EventLog.init(this)
        settings = Settings(this)
        val palette = Themes.palette(AppTheme.fromId(settings.theme))
        ui = Ui(this, palette)
        applyWindowTheme(this, palette, barColor = palette.surface)
        api = ApiClient(settings.serverUrl, settings, log = EventLog::log)
        items = ViewerSession.items.toMutableList()
        if (items.isEmpty()) {
            finish()
            return
        }
        index = intent.getIntExtra(EXTRA_INDEX, 0).coerceIn(0, items.lastIndex)

        title = ui.text("", 14f, bold = true).apply { maxLines = 1; ellipsize = android.text.TextUtils.TruncateAt.MIDDLE }
        subtitle = ui.muted("", 11f)
        star = ui.text("", 22f, palette.ink).apply {
            gravity = Gravity.CENTER
            setPadding(ui.dp(12), 0, ui.dp(12), 0)
            setOnClickListener { toggleFavorite() }
        }
        val back = ui.text("<", 22f, palette.ink, bold = true).apply {
            setPadding(ui.dp(14), 0, ui.dp(14), 0)
            setOnClickListener { finish() }
        }
        val info = ui.text("i", 18f, palette.ink, bold = true).apply {
            gravity = Gravity.CENTER
            setPadding(ui.dp(12), 0, ui.dp(12), 0)
            setOnClickListener { showInfo() }
        }
        val openWith = ui.text("Open with", 12f, palette.mute).apply {
            setPadding(ui.dp(10), 0, ui.dp(12), 0)
            setOnClickListener { openWithOtherApp() }
        }
        val bar = ui.horizontal().apply {
            setBackgroundColor(palette.surface)
            minimumHeight = ui.dp(52)
            addView(back)
            addView(
                ui.vertical().apply { addView(title); addView(subtitle) },
                LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f),
            )
            addView(star)
            addView(info)
            addView(openWith)
        }

        stage = FrameLayout(this).apply { setBackgroundColor(palette.bg) }
        prevButton = navButton("<") { go(-1) }
        nextButton = navButton(">") { go(1) }
        stage.post { /* buttons are added after content so they stay on top */ }

        val root = FrameLayout(this).apply {
            setBackgroundColor(palette.bg)
            addView(
                ui.vertical().apply {
                    addView(bar, ui.matchWidth())
                    addView(ui.divider())
                    addView(stage, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
                },
            )
            addView(prevButton, FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.START or Gravity.CENTER_VERTICAL))
            addView(nextButton, FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.END or Gravity.CENTER_VERTICAL))
        }
        setContentView(root)
        show()
    }

    private fun navButton(label: String, onClick: () -> Unit): TextView =
        ui.text(label, 26f, ui.palette.ink, bold = true).apply {
            gravity = Gravity.CENTER
            setPadding(ui.dp(14), ui.dp(14), ui.dp(14), ui.dp(14))
            background = ui.box(ui.palette.surface, ui.palette.line, radiusDp = if (ui.palette.retro) 0 else 8)
            alpha = 0.85f
            setOnClickListener { onClick() }
            val params = ViewGroup.MarginLayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT)
            params.setMargins(ui.dp(6), 0, ui.dp(6), 0)
            layoutParams = params
        }

    /** Swipe left/right to move between files when the picture is not zoomed. */
    override fun dispatchTouchEvent(ev: MotionEvent): Boolean {
        val z = zoom
        if (z != null && !z.isZoomed) {
            when (ev.actionMasked) {
                MotionEvent.ACTION_DOWN -> swipeStartX = ev.x
                MotionEvent.ACTION_UP -> {
                    val dx = ev.x - swipeStartX
                    if (kotlin.math.abs(dx) > ui.dp(90)) go(if (dx < 0) 1 else -1)
                }
            }
        }
        return super.dispatchTouchEvent(ev)
    }

    private fun go(delta: Int) {
        val next = index + delta
        if (next in items.indices) {
            index = next
            show()
        }
    }

    private fun current() = items[index]

    private fun show() {
        generation++
        val gen = generation
        releaseCurrent()
        val file = current()
        title.text = file.name
        subtitle.text = "${index + 1} of ${items.size}  |  ${fmtBytes(file.size)}"
        star.text = if (file.favorite) "★" else "☆"
        star.setTextColor(if (file.favorite) ui.palette.ink else ui.palette.mute)
        prevButton.visibility = if (index > 0) View.VISIBLE else View.GONE
        nextButton.visibility = if (index < items.lastIndex) View.VISIBLE else View.GONE
        stage.removeAllViews()
        when (viewerKind(file.name, file.mime)) {
            ViewerKind.IMAGE -> showImage(file, gen)
            ViewerKind.VIDEO -> showMedia(file, gen)
            ViewerKind.AUDIO -> showAudio(file, gen)
            ViewerKind.PDF -> showPdf(file, gen)
            ViewerKind.TEXT -> showText(file, gen)
            ViewerKind.OTHER -> showOther(file)
        }
    }

    private fun releaseCurrent() {
        video?.stopPlayback()
        video = null
        audio?.let { runCatching { it.release() } }
        audio = null
        zoom = null
        pdf?.close()
        pdf = null
    }

    private fun message(text: String): TextView = ui.text(text, 14f, ui.palette.mute).apply {
        gravity = Gravity.CENTER
        setPadding(ui.dp(24), ui.dp(24), ui.dp(24), ui.dp(24))
    }

    private fun putCentered(view: View) {
        stage.addView(view, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT, Gravity.CENTER))
    }

    // ---------------------------------------------------------------- image

    private fun showImage(file: RemoteItem, gen: Int) {
        val view = ZoomImageView(this)
        zoom = view
        putCentered(view)
        val loading = message("Loading...")
        stage.addView(loading)
        val screen = maxOf(resources.displayMetrics.widthPixels, resources.displayMetrics.heightPixels)
        thread {
            // A quick, small version first, then the sharp one.
            val preview = try { ThumbLoader.fetch(api.thumbnailUrl(file.id, 1024), 1024) } catch (e: Exception) { null }
            runOnUiThread {
                if (gen == generation && preview != null) {
                    view.setImageBitmap(preview)
                    stage.removeView(loading)
                }
            }
            val full = try { ThumbLoader.fetch(api.contentUrl(file.id), minOf(screen * 2, 4096)) } catch (e: Exception) { null }
            runOnUiThread {
                if (gen != generation) return@runOnUiThread
                if (full != null) {
                    view.setImageBitmap(full)
                    stage.removeView(loading)
                } else if (preview == null) {
                    loading.text = "This image could not be shown here.\nTap \"Open with\" to use another app."
                }
            }
        }
    }


    // ---------------------------------------------------------------- audio

    private var audio: android.media.MediaPlayer? = null
    private val audioTicker = android.os.Handler(android.os.Looper.getMainLooper())

    /** A small player of our own (the stock media controller does not show up reliably). */
    private fun showAudio(file: RemoteItem, gen: Int) {
        val loading = message("Loading...")
        stage.addView(loading)
        thread {
            val url = try { api.contentUrl(file.id) } catch (e: Exception) { null }
            runOnUiThread {
                if (gen != generation) return@runOnUiThread
                if (url == null) {
                    loading.text = "Could not reach the server."
                    return@runOnUiThread
                }
                val player = android.media.MediaPlayer()
                audio = player
                player.setAudioAttributes(
                    android.media.AudioAttributes.Builder()
                        .setContentType(android.media.AudioAttributes.CONTENT_TYPE_MUSIC)
                        .setUsage(android.media.AudioAttributes.USAGE_MEDIA)
                        .build(),
                )
                player.setOnErrorListener { _, _, _ ->
                    loading.text = "This file could not be played here.\nTap \"Open with\" to use another app."
                    if (loading.parent == null) stage.addView(loading)
                    true
                }
                player.setOnPreparedListener { p ->
                    if (gen != generation) return@setOnPreparedListener
                    stage.removeView(loading)
                    val seek = android.widget.SeekBar(this).apply { max = maxOf(p.duration, 1) }
                    val time = ui.muted("0:00 / ${clock(p.duration)}", 13f).apply { gravity = Gravity.CENTER }
                    lateinit var toggle: android.widget.Button
                    toggle = ui.button("Pause", primary = true) {
                        if (p.isPlaying) { p.pause(); toggle.text = "Play" } else { p.start(); toggle.text = "Pause" }
                    }
                    val back = ui.button("-10s") { p.seekTo((p.currentPosition - 10_000).coerceAtLeast(0)) }
                    val forward = ui.button("+10s") { p.seekTo((p.currentPosition + 10_000).coerceAtMost(p.duration)) }
                    seek.setOnSeekBarChangeListener(object : android.widget.SeekBar.OnSeekBarChangeListener {
                        override fun onProgressChanged(bar: android.widget.SeekBar?, value: Int, fromUser: Boolean) {
                            if (fromUser) p.seekTo(value)
                        }
                        override fun onStartTrackingTouch(bar: android.widget.SeekBar?) {}
                        override fun onStopTrackingTouch(bar: android.widget.SeekBar?) {}
                    })
                    p.setOnCompletionListener { toggle.text = "Play" }
                    val controls = ui.horizontal().apply {
                        gravity = Gravity.CENTER
                        addView(back)
                        addView(android.view.View(this@ViewerActivity), LinearLayout.LayoutParams(ui.dp(10), 1))
                        addView(toggle)
                        addView(android.view.View(this@ViewerActivity), LinearLayout.LayoutParams(ui.dp(10), 1))
                        addView(forward)
                    }
                    putCentered(
                        ui.vertical().apply {
                            gravity = Gravity.CENTER
                            setPadding(ui.dp(24), 0, ui.dp(24), 0)
                            addView(ui.badge(typeBadge(file.name), 96))
                            addView(ui.text(file.name, 14f).apply { gravity = Gravity.CENTER; setPadding(0, ui.dp(12), 0, ui.dp(20)) })
                            addView(seek, ui.matchWidth())
                            addView(time, ui.matchWidth(4))
                            addView(controls, ui.matchWidth(16))
                        },
                    )
                    p.start()
                    val tick = object : Runnable {
                        override fun run() {
                            if (audio !== p || gen != generation) return
                            try {
                                seek.progress = p.currentPosition
                                time.text = "${clock(p.currentPosition)} / ${clock(p.duration)}"
                            } catch (_: IllegalStateException) {
                                return
                            }
                            audioTicker.postDelayed(this, 500)
                        }
                    }
                    audioTicker.post(tick)
                }
                try {
                    player.setDataSource(url)
                    player.prepareAsync()
                } catch (e: Exception) {
                    loading.text = "This file could not be played here.\nTap \"Open with\" to use another app."
                }
            }
        }
    }

    private fun clock(millis: Int): String {
        val total = millis / 1000
        return "${total / 60}:${String.format(java.util.Locale.US, "%02d", total % 60)}"
    }

    // ---------------------------------------------------------------- video

    private fun showMedia(file: RemoteItem, gen: Int) {
        val isAudio = viewerKind(file.name, file.mime) == ViewerKind.AUDIO
        val loading = message("Loading...")
        stage.addView(loading)
        thread {
            val url = try { api.contentUrl(file.id) } catch (e: Exception) { null }
            runOnUiThread {
                if (gen != generation) return@runOnUiThread
                if (url == null) {
                    loading.text = "Could not reach the server."
                    return@runOnUiThread
                }
                val player = VideoView(this)
                val controller = MediaController(this).apply { setAnchorView(player) }
                player.setMediaController(controller)
                player.setOnPreparedListener {
                    stage.removeView(loading)
                    player.start()
                    // Audio has no picture, so keep the transport controls on screen for good.
                    if (isAudio) controller.show(0)
                }
                player.setOnErrorListener { _, _, _ ->
                    loading.text = "This file could not be played here.\nTap \"Open with\" to use another app."
                    if (loading.parent == null) stage.addView(loading)
                    true
                }
                video = player
                if (isAudio) {
                    stage.addView(
                        ui.vertical().apply {
                            gravity = Gravity.CENTER
                            addView(ui.badge(typeBadge(file.name), 96))
                            addView(ui.text(file.name, 14f).apply { gravity = Gravity.CENTER; setPadding(0, ui.dp(12), 0, 0) })
                        },
                        FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT, Gravity.CENTER),
                    )
                }
                stage.addView(player, if (isAudio) 1 else 0, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT, Gravity.CENTER))
                player.setVideoURI(Uri.parse(url))
            }
        }
    }

    // ---------------------------------------------------------------- text

    private fun showText(file: RemoteItem, gen: Int) {
        val loading = message("Loading...")
        stage.addView(loading)
        thread {
            val limit = 2L * 1024 * 1024
            val target = File(cacheDir, "viewer/${file.id}.txt")
            val result = try {
                api.downloadContent(file.id, target, maxBytes = limit)
                target.readText(Charsets.UTF_8)
            } catch (e: Exception) {
                null
            } finally {
                target.delete()
            }
            runOnUiThread {
                if (gen != generation) return@runOnUiThread
                stage.removeView(loading)
                if (result == null) {
                    stage.addView(message("This file could not be loaded."))
                    return@runOnUiThread
                }
                val body = ui.text(result, 12f).apply {
                    typeface = android.graphics.Typeface.MONOSPACE
                    setTextIsSelectable(true)
                    setPadding(ui.dp(14), ui.dp(12), ui.dp(14), ui.dp(24))
                }
                val column = ui.vertical()
                if (file.size > limit) column.addView(ui.muted("Showing the first ${fmtBytes(limit)}. Use Open with for the rest.", 11f).apply { setPadding(ui.dp(14), ui.dp(8), ui.dp(14), 0) })
                column.addView(body)
                stage.addView(ScrollView(this).apply { addView(column) })
            }
        }
    }

    // ---------------------------------------------------------------- PDF

    private inner class PdfSession(val file: File) {
        private val descriptor = ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY)
        private val renderer = PdfRenderer(descriptor)
        private val worker = Executors.newSingleThreadExecutor()
        private val cache = android.util.LruCache<Int, Bitmap>(8)
        val pageCount: Int get() = renderer.pageCount

        fun render(page: Int, widthPx: Int, onDone: (Bitmap?) -> Unit) {
            cache.get(page)?.let { onDone(it); return }
            worker.execute {
                val bitmap = try {
                    synchronized(renderer) {
                        renderer.openPage(page).use { p ->
                            val height = (widthPx.toFloat() * p.height / p.width).toInt().coerceAtLeast(1)
                            val bmp = Bitmap.createBitmap(widthPx, height, Bitmap.Config.ARGB_8888)
                            bmp.eraseColor(android.graphics.Color.WHITE)
                            p.render(bmp, null, null, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY)
                            bmp
                        }
                    }
                } catch (e: Exception) {
                    null
                }
                if (bitmap != null) cache.put(page, bitmap)
                runOnUiThread { onDone(bitmap) }
            }
        }

        fun close() {
            worker.shutdownNow()
            try { synchronized(renderer) { renderer.close() } } catch (_: Exception) { }
            try { descriptor.close() } catch (_: Exception) { }
            file.delete()
        }
    }

    private fun showPdf(file: RemoteItem, gen: Int) {
        val loading = message("Loading PDF...")
        stage.addView(loading)
        thread {
            val target = File(cacheDir, "viewer/${file.id}.pdf")
            val ok = try {
                api.downloadContent(file.id, target) { done, total ->
                    if (total > 0) runOnUiThread { if (gen == generation) loading.text = "Loading PDF... ${done * 100 / total}%" }
                }
                true
            } catch (e: Exception) {
                false
            }
            runOnUiThread {
                if (gen != generation) {
                    target.delete()
                    return@runOnUiThread
                }
                if (!ok) {
                    loading.text = "The PDF could not be downloaded."
                    return@runOnUiThread
                }
                val session = try { PdfSession(target) } catch (e: Exception) {
                    loading.text = "This PDF could not be opened here.\nTap \"Open with\" to use another app."
                    target.delete()
                    return@runOnUiThread
                }
                pdf = session
                stage.removeView(loading)
                val list = RecyclerView(this).apply {
                    layoutManager = LinearLayoutManager(this@ViewerActivity)
                    adapter = PdfAdapter(session)
                    setBackgroundColor(ui.palette.line)
                }
                stage.addView(list, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
            }
        }
    }

    private inner class PdfAdapter(private val session: PdfSession) : RecyclerView.Adapter<RecyclerView.ViewHolder>() {
        override fun getItemCount() = session.pageCount

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): RecyclerView.ViewHolder {
            val image = ImageView(this@ViewerActivity).apply {
                adjustViewBounds = true
                scaleType = ImageView.ScaleType.FIT_CENTER
                setBackgroundColor(android.graphics.Color.WHITE)
                layoutParams = RecyclerView.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ui.dp(480)).apply {
                    setMargins(0, 0, 0, ui.dp(6))
                }
            }
            return object : RecyclerView.ViewHolder(image) {}
        }

        override fun onBindViewHolder(holder: RecyclerView.ViewHolder, position: Int) {
            val image = holder.itemView as ImageView
            image.tag = position
            image.setImageDrawable(null)
            val width = (resources.displayMetrics.widthPixels * 1.5f).toInt()
            session.render(position, width) { bitmap ->
                if (image.tag == position && bitmap != null) {
                    image.setImageBitmap(bitmap)
                    image.layoutParams = (image.layoutParams as RecyclerView.LayoutParams).apply {
                        height = ViewGroup.LayoutParams.WRAP_CONTENT
                    }
                }
            }
        }
    }

    // ---------------------------------------------------------------- other

    private fun showOther(file: RemoteItem) {
        val column = ui.vertical().apply {
            gravity = Gravity.CENTER
            setPadding(ui.dp(24), ui.dp(24), ui.dp(24), ui.dp(24))
            addView(ui.badge(typeBadge(file.name), 96))
            addView(ui.text("The app can't show this type of file itself.", 14f).apply {
                gravity = Gravity.CENTER
                setPadding(0, ui.dp(16), 0, ui.dp(12))
            })
            addView(ui.button("Open with another app", primary = true) { openWithOtherApp() })
        }
        putCentered(column)
    }

    /** Downloads the file to the cache and hands it to whichever app the user picks. */
    private fun openWithOtherApp() {
        val file = current()
        val notice = message("Preparing ${file.name}...")
        stage.addView(notice)
        thread {
            val target = File(cacheDir, "viewer/${file.id}-${file.name.replace('/', '_')}")
            val ok = try {
                api.downloadContent(file.id, target)
                true
            } catch (e: Exception) {
                EventLog.log("open-with download failed: ${e.message}")
                false
            }
            runOnUiThread {
                stage.removeView(notice)
                if (!ok) {
                    stage.addView(message("Could not download the file."))
                    return@runOnUiThread
                }
                val uri = FileProvider.getUriForFile(this, "$packageName.files", target)
                val send = Intent(Intent.ACTION_VIEW).apply {
                    setDataAndType(uri, file.mime.ifEmpty { "*/*" })
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                }
                try {
                    startActivity(Intent.createChooser(send, "Open ${file.name} with"))
                } catch (e: Exception) {
                    stage.addView(message("No app on this phone can open this file."))
                }
            }
        }
    }

    // ---------------------------------------------------------------- actions

    private fun toggleFavorite() {
        val file = current()
        val wanted = !file.favorite
        items[index] = file.copy(favorite = wanted)
        star.text = if (wanted) "★" else "☆"
        star.setTextColor(if (wanted) ui.palette.ink else ui.palette.mute)
        thread {
            try {
                api.setFavorite(file.id, wanted)
            } catch (e: Exception) {
                EventLog.log("favorite failed: ${e.message}")
                runOnUiThread {
                    items[index] = file
                    star.text = if (file.favorite) "★" else "☆"
                }
            }
        }
    }

    private fun showInfo() {
        val file = current()
        val text = buildString {
            appendLine("Name: ${file.name}")
            appendLine("Type: ${file.mime.ifEmpty { "unknown" }}")
            appendLine("Size: ${fmtBytes(file.size)}")
            file.takenAtMillis?.let { appendLine("Taken: ${fmtDate(it)}") }
            file.modifiedAtMillis?.let { appendLine("Modified: ${fmtDate(it)}") }
            appendLine("Uploaded: ${fmtDate(file.createdAtMillis)}")
            append("Folder: ${file.folderPath.ifEmpty { "My files" }}")
        }
        AlertDialog.Builder(this).setTitle("Details").setMessage(text).setPositiveButton("OK", null).show()
    }

    override fun onDestroy() {
        releaseCurrent()
        super.onDestroy()
    }

    companion object {
        const val EXTRA_INDEX = "index"
    }
}
