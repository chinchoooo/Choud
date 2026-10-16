package cloud.personal.sync

import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import androidx.recyclerview.widget.GridLayoutManager
import androidx.recyclerview.widget.RecyclerView
import kotlin.concurrent.thread

/** Every photo and video from every folder, newest first, grouped by month. */
class PhotosTab(private val host: Host) : Tab {
    private val ui = host.ui
    private val palette = ui.palette

    private val pageSize = 120
    private var kind = "all"
    private val items = ArrayList<RemoteItem>()
    private var rows: List<PhotoRow> = emptyList()
    private var total = 0
    private var loading = false
    private var error: String? = null
    private var loadedOnce = false

    private val statusView = ui.muted("", 12f)
    private val list = RecyclerView(ui.context)
    private val adapter = Adapter()
    private val filterButtons = LinkedHashMap<String, TextView>()
    private val spans = 3

    override val view: View = ui.vertical().apply {
        setBackgroundColor(palette.bg)
        val filters = ui.horizontal().apply {
            setPadding(ui.dp(12), ui.dp(8), ui.dp(12), ui.dp(4))
            for ((id, label) in listOf("all" to "All", "image" to "Photos", "video" to "Videos")) {
                val button = ui.button(label) {
                    if (kind != id) {
                        kind = id
                        reload()
                    }
                }
                filterButtons[id] = button
                addView(button)
                addView(View(ui.context), LinearLayout.LayoutParams(ui.dp(6), 1))
            }
            addView(View(ui.context), LinearLayout.LayoutParams(0, 1, 1f))
            addView(ui.button("Refresh") { reload() })
        }
        addView(filters, ui.matchWidth())
        addView(statusView, ui.matchWidth().apply { leftMargin = ui.dp(14); rightMargin = ui.dp(14) })
        val grid = GridLayoutManager(ui.context, spans).apply {
            spanSizeLookup = object : GridLayoutManager.SpanSizeLookup() {
                override fun getSpanSize(position: Int) = if (rows.getOrNull(position) is PhotoRow.Header) spans else 1
            }
        }
        list.layoutManager = grid
        list.adapter = adapter
        list.addOnScrollListener(object : RecyclerView.OnScrollListener() {
            override fun onScrolled(rv: RecyclerView, dx: Int, dy: Int) {
                if (dy <= 0 || loading || items.size >= total) return
                val last = grid.findLastVisibleItemPosition()
                if (last >= rows.size - 12) loadMore()
            }
        })
        addView(list, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
    }

    override fun onShow() {
        if (!loadedOnce) reload()
    }

    private fun reload() {
        loadedOnce = true
        items.clear()
        rows = emptyList()
        total = 0
        error = null
        updateFilters()
        adapter.notifyDataSetChanged()
        loadMore()
    }

    private fun updateFilters() {
        for ((id, button) in filterButtons) {
            val active = id == kind
            button.alpha = if (active) 1f else 0.6f
            button.setTypeface(button.typeface, if (active) android.graphics.Typeface.BOLD else android.graphics.Typeface.NORMAL)
        }
    }

    private fun loadMore() {
        if (loading) return
        loading = true
        val wantedKind = kind
        val offset = items.size
        refreshStatus()
        thread {
            try {
                val page = host.api.listPhotos(wantedKind, offset, pageSize)
                host.runOnUi {
                    if (wantedKind != kind || offset != items.size) return@runOnUi
                    items.addAll(page.items)
                    total = page.total
                    rows = groupByMonth(items)
                    loading = false
                    error = null
                    adapter.notifyDataSetChanged()
                    refreshStatus()
                }
            } catch (e: Exception) {
                EventLog.log("photos: could not load: ${e.javaClass.simpleName}: ${e.message}")
                host.runOnUi {
                    loading = false
                    error = e.message ?: e.javaClass.simpleName
                    refreshStatus()
                }
            }
        }
    }

    private fun refreshStatus() {
        statusView.text = when {
            error != null -> "Could not load: $error (tap Refresh)"
            loading && items.isEmpty() -> "Loading..."
            items.isEmpty() -> "No photos or videos yet."
            else -> "${items.size} of $total, newest first"
        }
        statusView.setTextColor(if (error != null) palette.danger else palette.mute)
    }

    private inner class Adapter : RecyclerView.Adapter<RecyclerView.ViewHolder>() {
        override fun getItemCount() = rows.size
        override fun getItemViewType(position: Int) = if (rows[position] is PhotoRow.Header) 0 else 1

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): RecyclerView.ViewHolder {
            if (viewType == 0) {
                val heading = ui.text("", 14f, palette.mute, bold = true).apply {
                    setPadding(ui.dp(14), ui.dp(14), ui.dp(14), ui.dp(6))
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
            val marker = ui.text("", 11f, palette.accentInk, bold = true).apply {
                setBackgroundColor(palette.accent)
                setPadding(ui.dp(4), 0, ui.dp(4), 0)
            }
            cell.addView(marker, FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.BOTTOM or Gravity.END))
            return PhotoHolder(cell, image, marker)
        }

        override fun onBindViewHolder(holder: RecyclerView.ViewHolder, position: Int) {
            when (val row = rows[position]) {
                is PhotoRow.Header -> (holder.itemView as TextView).text = row.label
                is PhotoRow.Photo -> {
                    val h = holder as PhotoHolder
                    val file = row.item
                    val isVideo = viewerKind(file.name, file.mime) == ViewerKind.VIDEO
                    h.marker.visibility = if (isVideo || file.favorite) View.VISIBLE else View.GONE
                    h.marker.text = when {
                        isVideo && file.favorite -> "VIDEO ★"
                        isVideo -> "VIDEO"
                        else -> "★"
                    }
                    ThumbLoader.load(
                        h.image, "t:${file.id}:256", 256,
                        urlProvider = { host.api.thumbnailUrl(file.id, 256) },
                    )
                    h.itemView.setOnClickListener { host.openViewer(items.toList(), row.indexInAll) }
                }
            }
        }
    }

    private class PhotoHolder(cell: FrameLayout, val image: ImageView, val marker: TextView) : RecyclerView.ViewHolder(cell)
}
