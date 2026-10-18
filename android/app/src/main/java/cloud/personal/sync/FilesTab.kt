package cloud.personal.sync

import android.text.TextUtils
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.HorizontalScrollView
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import kotlin.concurrent.thread

/** Browse the server's folders and files, with thumbnails; tap a file to open the built-in viewer. */
class FilesTab(private val host: Host) : Tab {
    private val ui = host.ui
    private val palette = ui.palette

    private class Crumb(val id: String?, val name: String)

    private val trail = ArrayList<Crumb>().apply { add(Crumb(null, "My files")) }
    private var folders: List<FolderItem> = emptyList()
    private var files: MutableList<RemoteItem> = mutableListOf()
    private var loading = false
    private var error: String? = null
    private var loadedOnce = false

    private val crumbRow = ui.horizontal()
    private val statusView = ui.muted("", 13f)
    private val list = RecyclerView(ui.context)
    private val adapter = Adapter()
    private val swipe = SwipeRefreshLayout(ui.context).apply {
        setColorSchemeColors(palette.ink)
        setProgressBackgroundColorSchemeColor(palette.surface)
    }

    override val view: View = ui.vertical().apply {
        setBackgroundColor(palette.bg)
        val top = ui.horizontal().apply {
            setPadding(ui.dp(12), ui.dp(8), ui.dp(12), ui.dp(4))
            addView(
                HorizontalScrollView(ui.context).apply {
                    isHorizontalScrollBarEnabled = false
                    addView(crumbRow)
                },
                LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f),
            )
            addView(ui.button("Refresh") { reload() })
        }
        addView(top, ui.matchWidth())
        addView(statusView, ui.matchWidth().apply { leftMargin = ui.dp(14); rightMargin = ui.dp(14) })
        list.layoutManager = LinearLayoutManager(ui.context)
        list.adapter = adapter
        swipe.addView(list)
        swipe.setOnRefreshListener { reload() }
        addView(swipe, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
    }

    private var loadedAt = 0L
    private val currentId: String? get() = trail.last().id

    override fun onShow() {
        // Coming back to the tab refreshes a listing that is more than half a minute old.
        if (!loadedOnce || System.currentTimeMillis() - loadedAt > 30_000) reload()
    }

    override fun onBack(): Boolean {
        if (trail.size <= 1) return false
        trail.removeAt(trail.lastIndex)
        reload()
        return true
    }

    private fun reload() {
        loadedOnce = true
        loading = true
        error = null
        render()
        val id = currentId
        thread {
            try {
                val listing = host.api.listDirectory(id)
                host.runOnUi {
                    if (id != currentId) return@runOnUi // navigated away meanwhile
                    folders = listing.folders
                    files = listing.files.toMutableList()
                    loading = false
                    render()
                }
            } catch (e: Exception) {
                EventLog.log("files: could not load folder $id: ${e.javaClass.simpleName}: ${e.message}")
                host.runOnUi {
                    loading = false
                    error = e.message ?: e.javaClass.simpleName
                    // Offline: show what is kept on this phone so it can still be opened.
                    val kept = OfflineStore.items(host.ui.context)
                    if (kept.isNotEmpty()) {
                        folders = emptyList()
                        files = kept.toMutableList()
                    }
                    render()
                }
            }
        }
    }

    private fun render() {
        swipe.isRefreshing = loading
        if (!loading) loadedAt = System.currentTimeMillis()
        crumbRow.removeAllViews()
        trail.forEachIndexed { index, crumb ->
            val last = index == trail.lastIndex
            crumbRow.addView(
                ui.text(if (index > 0) " / ${crumb.name}" else crumb.name, 14f, if (last) palette.ink else palette.mute, bold = last)
                    .apply {
                        setPadding(0, ui.dp(6), 0, ui.dp(6))
                        if (!last) setOnClickListener {
                            while (trail.size > index + 1) trail.removeAt(trail.lastIndex)
                            reload()
                        }
                    },
            )
        }
        statusView.text = when {
            loading -> "Loading..."
            error != null && files.isNotEmpty() -> "Server not reachable. Showing the ${files.size} file(s) kept on this phone."
            error != null -> "Could not load: $error (tap Refresh)"
            folders.isEmpty() && files.isEmpty() -> "This folder is empty."
            else -> "${folders.size} folder${if (folders.size == 1) "" else "s"}, ${files.size} file${if (files.size == 1) "" else "s"}"
        }
        statusView.setTextColor(if (error != null) palette.danger else palette.mute)
        adapter.notifyDataSetChanged()
    }

    private inner class Holder(val root: LinearLayout) : RecyclerView.ViewHolder(root) {
        val thumbBox = FrameLayout(ui.context)
        val badge = ui.badge("", 52)
        val image = ImageView(ui.context).apply { scaleType = ImageView.ScaleType.CENTER_CROP }
        val name = ui.text("", 14f).apply { maxLines = 1; ellipsize = TextUtils.TruncateAt.MIDDLE }
        val sub = ui.muted("", 12f)
        val star = ui.text("", 20f, palette.mute).apply {
            gravity = Gravity.CENTER
            setPadding(ui.dp(10), 0, ui.dp(6), 0)
        }

        init {
            thumbBox.addView(badge)
            thumbBox.addView(image, FrameLayout.LayoutParams(ui.dp(52), ui.dp(52)))
            root.addView(thumbBox, LinearLayout.LayoutParams(ui.dp(52), ui.dp(52)))
            val texts = ui.vertical().apply {
                setPadding(ui.dp(12), 0, ui.dp(4), 0)
                addView(name)
                addView(sub)
            }
            root.addView(texts, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
            root.addView(star)
        }
    }

    private inner class Adapter : RecyclerView.Adapter<Holder>() {
        override fun getItemCount() = folders.size + files.size

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): Holder {
            val row = ui.horizontal().apply {
                setPadding(ui.dp(14), ui.dp(7), ui.dp(8), ui.dp(7))
                layoutParams = RecyclerView.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
                isClickable = true
                isFocusable = true
            }
            return Holder(row)
        }

        override fun onBindViewHolder(holder: Holder, position: Int) {
            if (position < folders.size) {
                val folder = folders[position]
                holder.name.text = folder.name
                holder.sub.text = "Folder"
                holder.badge.text = "DIR"
                holder.badge.visibility = View.VISIBLE
                holder.image.tag = null
                holder.image.setImageDrawable(null)
                holder.star.text = ""
                holder.star.setOnClickListener(null)
                holder.root.setOnClickListener {
                    trail.add(Crumb(folder.id, folder.name))
                    reload()
                }
                return
            }
            val index = position - folders.size
            val file = files[index]
            holder.name.text = file.name
            holder.sub.text = "${fmtBytes(file.size)}  |  ${fmtDate(file.displayMillis)}" +
                if (OfflineStore.has(host.ui.context, file.id)) "  |  on this phone" else ""
            holder.badge.text = typeBadge(file.name)
            holder.badge.visibility = View.VISIBLE
            val kind = viewerKind(file.name, file.mime)
            if (kind == ViewerKind.IMAGE || kind == ViewerKind.VIDEO) {
                ThumbLoader.load(
                    holder.image, "t:${file.id}:256", 256,
                    urlProvider = { host.api.thumbnailUrl(file.id, 256) },
                    onFail = { holder.badge.visibility = View.VISIBLE },
                )
                holder.badge.visibility = View.GONE
            } else {
                holder.image.tag = null
                holder.image.setImageDrawable(null)
            }
            holder.star.text = if (file.favorite) "★" else "☆"
            holder.star.setTextColor(if (file.favorite) palette.ink else palette.mute)
            holder.star.setOnClickListener {
                val wanted = !file.favorite
                files[index] = file.copy(favorite = wanted)
                adapter.notifyItemChanged(position)
                thread {
                    try {
                        host.api.setFavorite(file.id, wanted)
                    } catch (e: Exception) {
                        EventLog.log("favorite failed: ${e.message}")
                        host.runOnUi {
                            files[index] = file
                            adapter.notifyItemChanged(position)
                        }
                    }
                }
            }
            holder.root.setOnClickListener { host.openViewer(files.toList(), index) }
        }
    }
}
