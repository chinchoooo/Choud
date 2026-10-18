package cloud.personal.sync

import android.view.Gravity
import android.view.HapticFeedbackConstants
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import androidx.recyclerview.widget.GridLayoutManager
import androidx.recyclerview.widget.RecyclerView
import androidx.recyclerview.widget.SimpleItemAnimator
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import kotlin.concurrent.thread

/** Every photo and video from every folder, newest first, grouped by month. */
class PhotosTab(private val host: Host) : Tab {
    private val ui = host.ui
    private val palette = ui.palette

    private val db by lazy { LibraryDb(ui.context) }
    private var kind = "all"
    private val items = ArrayList<RemoteItem>()
    private var rows: List<PhotoRow> = emptyList()
    private var total = 0
    private var loading = false
    private var error: String? = null
    private var loadedOnce = false
    private var loadedAt = 0L

    private val countView = ui.muted("", 12f)
    private val list = RecyclerView(ui.context)
    private val adapter = Adapter()
    private val spans = 3
    private val skeleton = Skeleton(ui, 10)
    private val stateHost = FrameLayout(ui.context)
    private val swipe = SwipeRefreshLayout(ui.context).apply {
        setColorSchemeColors(palette.ink)
        setProgressBackgroundColorSchemeColor(palette.surface)
    }

    // Selection: long-press a photo to start; tap photos (or a month heading) to add or remove.
    private var selecting = false
    private val selected = LinkedHashSet<String>()
    private val bulk by lazy { Bulk(host, ui.context) }
    private lateinit var headerRow: View
    private val selectionBar = SelectionBar(
        ui,
        SelectionActions(
            onClose = { endSelection() },
            onSelectAll = { selectAll() },
            onShare = { bulk.shareLinks(chosen()) },
            onDownload = { bulk.download(chosen(), emptyList()) },
            onKeep = { bulk.keepOffline(chosen()) { adapter.notifyDataSetChanged() } },
            onFavorite = { favoriteSelection() },
            onMove = { bulk.move(chosen(), emptyList()) { endSelection(); reload() } },
            onDelete = { bulk.delete(chosen(), emptyList()) { endSelection(); reload() } },
        ),
    )
    private val filter = Segmented(ui, listOf("all" to "All", "image" to "Photos", "video" to "Videos"), "all") {
        kind = it
        reload()
    }

    override val view: View = ui.vertical().apply {
        setBackgroundColor(palette.bg)
        val header = ui.horizontal().apply {
            setPadding(ui.dp(12), ui.dp(10), ui.dp(16), ui.dp(8))
            addView(filter.view)
            addView(View(ui.context), LinearLayout.LayoutParams(0, 1, 1f))
            addView(countView)
        }
        headerRow = header
        addView(header, ui.matchWidth())
        addView(selectionBar.view, ui.matchWidth())
        selectionBar.view.visibility = View.GONE

        val grid = GridLayoutManager(ui.context, spans).apply {
            spanSizeLookup = object : GridLayoutManager.SpanSizeLookup() {
                override fun getSpanSize(position: Int) = if (rows.getOrNull(position) is PhotoRow.Header) spans else 1
            }
        }
        list.layoutManager = grid
        list.adapter = adapter
        // Smooth scrolling: keep more rows ready, no change animations, fixed-size cells.
        list.setHasFixedSize(true)
        list.setItemViewCacheSize(40)
        (list.itemAnimator as? SimpleItemAnimator)?.supportsChangeAnimations = false
        list.addOnScrollListener(object : RecyclerView.OnScrollListener() {
            override fun onScrolled(rv: RecyclerView, dx: Int, dy: Int) {
                if (dy == 0) return
                // Warm the thumbnails a few screens ahead, in the direction of travel.
                val last = grid.findLastVisibleItemPosition()
                val first = grid.findFirstVisibleItemPosition()
                val range = if (dy > 0) (last + 1)..(last + 60) else (first - 60) until first
                for (i in range) {
                    val row = rows.getOrNull(i) as? PhotoRow.Photo ?: continue
                    ThumbLoader.prefetchPhoto(host.api, row.item.id, row.item.version)
                }
            }
        })
        swipe.addView(list)
        swipe.setOnRefreshListener { reload() }
        stateHost.addFill(swipe)
        addView(stateHost, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
    }

    // ------------------------------------------------------------------ selection

    override fun onBack(): Boolean {
        if (!selecting) return false
        endSelection()
        return true
    }

    private fun chosen(): List<RemoteItem> = items.filter { it.id in selected }

    private fun startSelection() {
        if (selecting) return
        selecting = true
        headerRow.visibility = View.GONE
        selectionBar.view.visibility = View.VISIBLE
        swipe.isEnabled = false
    }

    private fun endSelection() {
        selecting = false
        selected.clear()
        headerRow.visibility = View.VISIBLE
        selectionBar.view.visibility = View.GONE
        swipe.isEnabled = true
        adapter.notifyDataSetChanged()
    }

    private fun refreshBar() {
        val picked = chosen()
        selectionBar.update(selected.size, hasFiles = picked.isNotEmpty(), hasFolders = false, allFavorite = picked.isNotEmpty() && picked.all { it.favorite })
    }

    private fun toggle(id: String) {
        if (!selected.add(id)) selected.remove(id)
        if (selected.isEmpty()) {
            endSelection()
            return
        }
        refreshBar()
        adapter.notifyDataSetChanged()
    }

    /** Tapping a month heading while selecting adds the whole month (or removes it if all are in). */
    private fun toggleMonth(headerPosition: Int) {
        val ids = ArrayList<String>()
        var i = headerPosition + 1
        while (i < rows.size && rows[i] is PhotoRow.Photo) {
            ids.add((rows[i] as PhotoRow.Photo).item.id)
            i++
        }
        if (ids.all { it in selected }) selected.removeAll(ids.toSet()) else selected.addAll(ids)
        if (selected.isEmpty()) {
            endSelection()
        } else {
            refreshBar()
            adapter.notifyDataSetChanged()
        }
    }

    private fun selectAll() {
        val all = selected.size == items.size
        selected.clear()
        if (!all) selected.addAll(items.map { it.id })
        refreshBar()
        adapter.notifyDataSetChanged()
    }

    private fun favoriteSelection() {
        val picked = chosen()
        val on = !picked.all { it.favorite }
        bulk.favorite(picked, on) {
            val ids = selected.toList()
            thread { runCatching { db.setFavorite(ids, on) } }
            for (i in items.indices) if (items[i].id in selected) items[i] = items[i].copy(favorite = on)
            rows = groupByMonth(items)
            adapter.notifyDataSetChanged()
            refreshBar()
        }
    }

    // -------------------------------------------------------------------- loading

    override fun onShow() {
        if (!loadedOnce || System.currentTimeMillis() - loadedAt > 30_000) reload()
    }

    /** Bumped by every reload so a slow answer for an older request never lands on the new list. */
    private var generation = 0

    /**
     * Paints the library from the phone's own database at once (every month, no network), then asks
     * the server only what changed since last time: usually a bodyless 304, otherwise a few rows.
     */
    private fun reload() {
        loadedOnce = true
        generation++
        val gen = generation
        val wantedKind = kind
        loading = true
        error = null
        refreshStatus()
        thread {
            try {
                val local = db.load(wantedKind)
                host.runOnUi { if (gen == generation) applyItems(local) }
            } catch (e: Exception) {
                EventLog.log("photos: local database unreadable: ${e.javaClass.simpleName}: ${e.message}")
            }
            try {
                val changed = Library.sync(db, host.api)
                val fresh = if (changed) db.load(wantedKind) else null
                host.runOnUi {
                    if (gen != generation) return@runOnUi
                    loading = false
                    error = null
                    if (fresh != null) applyItems(fresh) else refreshStatus()
                }
            } catch (e: Exception) {
                EventLog.log("photos: could not refresh: ${e.javaClass.simpleName}: ${e.message}")
                host.runOnUi {
                    if (gen != generation) return@runOnUi
                    loading = false
                    error = if (e is ApiError && e.status == 404) "Update your Choud server to see photos in this version of the app." else (e.message ?: e.javaClass.simpleName)
                    refreshStatus()
                }
            }
        }
    }

    private fun applyItems(list: List<RemoteItem>) {
        items.clear()
        items.addAll(list)
        total = items.size
        rows = groupByMonth(items)
        adapter.notifyDataSetChanged()
        refreshStatus()
        // Read ahead: the first screens' worth of thumbnails come in one batched request each.
        items.take(72).forEach { ThumbLoader.prefetchPhoto(host.api, it.id, it.version) }
    }

    private fun showState(content: View?) {
        // Anything but the grid sits on top of it: skeleton while loading, empty/error afterwards.
        if (stateHost.childCount > 1) stateHost.removeViewAt(1)
        skeleton.stop()
        if (content != null) {
            stateHost.addView(content, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT).apply { gravity = Gravity.TOP })
        }
    }

    private fun refreshStatus() {
        swipe.isRefreshing = loading && items.isNotEmpty()
        if (!loading) loadedAt = System.currentTimeMillis()
        countView.text = if (items.isEmpty()) "" else "${items.size} item${if (items.size == 1) "" else "s"}"
        when {
            loading && items.isEmpty() -> {
                showState(
                    ui.vertical().apply {
                        setBackgroundColor(palette.bg)
                        addView(skeleton.detached())
                    },
                )
                skeleton.start()
            }
            error != null && items.isEmpty() -> showState(
                ui.emptyState(R.drawable.ic_warning, "Could not load your photos", error ?: "", "Try again") { reload() }
                    .apply { setBackgroundColor(palette.bg) },
            )
            items.isEmpty() -> showState(
                ui.emptyState(R.drawable.ic_nav_photos, "No photos yet", "Back up your phone from the Backup tab and they will appear here.")
                    .apply { setBackgroundColor(palette.bg) },
            )
            else -> showState(null)
        }
    }

    // ---------------------------------------------------------------------- list

    private inner class Adapter : RecyclerView.Adapter<RecyclerView.ViewHolder>() {
        override fun getItemCount() = rows.size
        override fun getItemViewType(position: Int) = if (rows[position] is PhotoRow.Header) 0 else 1

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): RecyclerView.ViewHolder {
            if (viewType == 0) {
                val heading = ui.text("", 15f, bold = true).apply {
                    setPadding(ui.dp(16), ui.dp(18), ui.dp(16), ui.dp(8))
                    layoutParams = RecyclerView.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
                }
                return object : RecyclerView.ViewHolder(heading) {}
            }
            val cell = FrameLayout(ui.context).apply {
                layoutParams = RecyclerView.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
                setPadding(ui.dp(1), ui.dp(1), ui.dp(1), ui.dp(1))
            }
            val image = SquareImageView(ui.context).apply {
                scaleType = ImageView.ScaleType.CENTER_CROP
                setBackgroundColor(palette.line)
            }
            cell.addView(image, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
            val marker = ui.text("", 10f, palette.bg, bold = true).apply {
                background = ui.box(palette.ink, null, radiusDp = if (palette.retro) 0 else 4)
                setPadding(ui.dp(5), ui.dp(1), ui.dp(5), ui.dp(1))
            }
            cell.addView(
                marker,
                FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.BOTTOM or Gravity.END)
                    .apply { setMargins(0, 0, ui.dp(6), ui.dp(6)) },
            )
            val check = ui.icon(R.drawable.ic_check_circle, 24, palette.accent).apply { visibility = View.GONE }
            cell.addView(check, FrameLayout.LayoutParams(ui.dp(24), ui.dp(24), Gravity.TOP or Gravity.START).apply { setMargins(ui.dp(7), ui.dp(7), 0, 0) })
            return PhotoHolder(cell, image, marker, check)
        }

        override fun onBindViewHolder(holder: RecyclerView.ViewHolder, position: Int) {
            when (val row = rows[position]) {
                is PhotoRow.Header -> {
                    val title = holder.itemView as TextView
                    title.text = if (selecting) "${row.label}   (tap to select the month)" else row.label
                    title.setOnClickListener { if (selecting) toggleMonth(position) }
                }
                is PhotoRow.Photo -> {
                    val h = holder as PhotoHolder
                    val file = row.item
                    val isVideo = viewerKind(file.name, file.mime) == ViewerKind.VIDEO
                    h.marker.visibility = if (isVideo || file.favorite) View.VISIBLE else View.GONE
                    h.marker.text = when {
                        isVideo && file.favorite -> "VIDEO  ★"
                        isVideo -> "VIDEO"
                        else -> "★"
                    }
                    ThumbLoader.loadPhoto(h.image, host.api, file.id, file.version, file.thumbhash)
                    val picked = file.id in selected
                    h.check.visibility = if (picked) View.VISIBLE else View.GONE
                    h.image.alpha = if (picked) 0.5f else 1f
                    h.itemView.setOnClickListener {
                        if (selecting) toggle(file.id) else host.openViewer(items.toList(), row.indexInAll)
                    }
                    h.itemView.setOnLongClickListener {
                        it.performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
                        startSelection()
                        toggle(file.id)
                        true
                    }
                }
            }
        }
    }

    private class PhotoHolder(cell: FrameLayout, val image: ImageView, val marker: TextView, val check: ImageView) : RecyclerView.ViewHolder(cell)
}
