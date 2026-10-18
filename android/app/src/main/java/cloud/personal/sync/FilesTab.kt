package cloud.personal.sync

import android.graphics.Color
import android.text.TextUtils
import android.view.Gravity
import android.view.HapticFeedbackConstants
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.HorizontalScrollView
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import androidx.recyclerview.widget.SimpleItemAnimator
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
    private var loadedAt = 0L

    private val crumbRow = ui.horizontal()
    private val list = RecyclerView(ui.context)
    private val adapter = Adapter()
    private val skeleton = Skeleton(ui, 9)
    private val stateHost = FrameLayout(ui.context)
    private val swipe = SwipeRefreshLayout(ui.context).apply {
        setColorSchemeColors(palette.ink)
        setProgressBackgroundColorSchemeColor(palette.surface)
    }

    // Selection: long-press anything to start, tap to add or remove, the bar offers bulk actions.
    private var selecting = false
    private val selFiles = LinkedHashSet<String>()
    private val selFolders = LinkedHashSet<String>()
    private val bulk by lazy { Bulk(host, ui.context) }
    private lateinit var topRow: View
    private val selectionBar = SelectionBar(
        ui,
        SelectionActions(
            onClose = { endSelection() },
            onSelectAll = { selectAll() },
            onShare = { bulk.shareLinks(selectedFiles()) },
            onDownload = { bulk.download(selectedFiles(), selectedFolders()) },
            onKeep = { bulk.keepOffline(selectedFiles()) { adapter.notifyDataSetChanged() } },
            onFavorite = { favoriteSelection() },
            onMove = { bulk.move(selectedFiles(), selectedFolders()) { endSelection(); reload() } },
            onDelete = { bulk.delete(selectedFiles(), selectedFolders()) { endSelection(); reload() } },
        ),
    )

    override val view: View = ui.vertical().apply {
        setBackgroundColor(palette.bg)
        val top = ui.horizontal().apply {
            setPadding(ui.dp(12), ui.dp(4), ui.dp(4), ui.dp(4))
            addView(
                HorizontalScrollView(ui.context).apply {
                    isHorizontalScrollBarEnabled = false
                    addView(crumbRow)
                },
                LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f),
            )
            addView(ui.iconOnly(R.drawable.ic_refresh, "Refresh", palette.mute) { reload() })
        }
        topRow = top
        addView(top, ui.matchWidth())
        addView(selectionBar.view, ui.matchWidth())
        selectionBar.view.visibility = View.GONE
        addView(ui.divider())
        list.layoutManager = LinearLayoutManager(ui.context)
        list.adapter = adapter
        list.setHasFixedSize(true)
        list.setItemViewCacheSize(30)
        (list.itemAnimator as? SimpleItemAnimator)?.supportsChangeAnimations = false
        swipe.addView(list)
        swipe.setOnRefreshListener { reload() }
        stateHost.addView(swipe, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        addView(stateHost, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
    }

    private val currentId: String? get() = trail.last().id

    override fun onShow() {
        // Coming back to the tab refreshes a listing that is more than half a minute old.
        if (!loadedOnce || System.currentTimeMillis() - loadedAt > 30_000) reload()
    }

    override fun onBack(): Boolean {
        if (selecting) {
            endSelection()
            return true
        }
        if (trail.size <= 1) return false
        trail.removeAt(trail.lastIndex)
        reload()
        return true
    }

    // ------------------------------------------------------------------ selection

    private fun selectedFiles(): List<RemoteItem> = files.filter { it.id in selFiles }
    private fun selectedFolders(): List<FolderItem> = folders.filter { it.id in selFolders }

    private fun startSelection() {
        if (selecting) return
        selecting = true
        topRow.visibility = View.GONE
        selectionBar.view.visibility = View.VISIBLE
        swipe.isEnabled = false
    }

    private fun endSelection() {
        selecting = false
        selFiles.clear()
        selFolders.clear()
        topRow.visibility = View.VISIBLE
        selectionBar.view.visibility = View.GONE
        swipe.isEnabled = true
        adapter.notifyDataSetChanged()
    }

    private fun updateSelectionBar() {
        val picked = selectedFiles()
        selectionBar.update(
            selFiles.size + selFolders.size,
            hasFiles = selFiles.isNotEmpty(),
            hasFolders = selFolders.isNotEmpty(),
            allFavorite = picked.isNotEmpty() && picked.all { it.favorite },
        )
    }

    private fun toggle(set: MutableSet<String>, id: String) {
        if (!set.add(id)) set.remove(id)
        if (selFiles.isEmpty() && selFolders.isEmpty()) {
            // Removing the last item leaves selection mode, like a gallery does.
            endSelection()
            return
        }
        updateSelectionBar()
        adapter.notifyDataSetChanged()
    }

    private fun selectAll() {
        val everything = selFiles.size == files.size && selFolders.size == folders.size
        selFiles.clear()
        selFolders.clear()
        if (!everything) {
            selFiles.addAll(files.map { it.id })
            selFolders.addAll(folders.map { it.id })
        }
        updateSelectionBar()
        adapter.notifyDataSetChanged()
    }

    private fun favoriteSelection() {
        val picked = selectedFiles()
        val on = !picked.all { it.favorite }
        bulk.favorite(picked, on) {
            files = files.map { if (it.id in selFiles) it.copy(favorite = on) else it }.toMutableList()
            adapter.notifyDataSetChanged()
            updateSelectionBar()
        }
    }

    // -------------------------------------------------------------------- loading

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
                    // Read ahead for the thumbnails in this folder.
                    files.forEach { f ->
                        val kind = viewerKind(f.name, f.mime)
                        if (kind == ViewerKind.IMAGE || kind == ViewerKind.VIDEO) {
                            ThumbLoader.prefetch("t:${f.id}:256", 256) { host.api.thumbnailUrl(f.id, 256) }
                        }
                    }
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

    private fun showState(content: View?) {
        if (stateHost.childCount > 1) stateHost.removeViewAt(1)
        skeleton.stop()
        if (content != null) {
            stateHost.addView(content, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        }
    }

    private fun render() {
        swipe.isRefreshing = loading && (folders.isNotEmpty() || files.isNotEmpty())
        if (!loading) loadedAt = System.currentTimeMillis()
        renderCrumbs()
        adapter.notifyDataSetChanged()
        val empty = folders.isEmpty() && files.isEmpty()
        when {
            loading && empty -> {
                showState(ui.vertical().apply { setBackgroundColor(palette.bg); addView(skeleton.view) })
                skeleton.start()
            }
            error != null && empty -> showState(
                ui.emptyState(R.drawable.ic_warning, "Could not load this folder", error ?: "", "Try again") { reload() }.apply { setBackgroundColor(palette.bg) },
            )
            empty -> showState(
                ui.emptyState(R.drawable.ic_nav_files, "This folder is empty", "Files you upload or back up will show up here.").apply { setBackgroundColor(palette.bg) },
            )
            error != null -> {
                showState(null)
                host.toast("Server not reachable. Showing the ${files.size} file(s) kept on this phone.")
            }
            else -> showState(null)
        }
    }

    private fun renderCrumbs() {
        crumbRow.removeAllViews()
        trail.forEachIndexed { index, crumb ->
            val last = index == trail.lastIndex
            if (index > 0) crumbRow.addView(ui.text("/", 13f, palette.line).apply { setPadding(ui.dp(2), 0, ui.dp(2), 0) })
            crumbRow.addView(
                ui.text(crumb.name, 14f, if (last) palette.bg else palette.mute, bold = last).apply {
                    setPadding(ui.dp(10), ui.dp(6), ui.dp(10), ui.dp(6))
                    if (last) background = ui.box(palette.ink, null, radiusDp = if (palette.retro) 0 else 14)
                    if (!last) setOnClickListener {
                        while (trail.size > index + 1) trail.removeAt(trail.lastIndex)
                        reload()
                    }
                },
            )
        }
    }

    // ---------------------------------------------------------------------- list

    private inner class Holder(val root: LinearLayout) : RecyclerView.ViewHolder(root) {
        val thumbBox = FrameLayout(ui.context)
        val badge = ui.badge("", 44)
        val folderIcon = ui.icon(R.drawable.ic_nav_files, 26, palette.ink).apply { visibility = View.GONE }
        val image = ImageView(ui.context).apply { scaleType = ImageView.ScaleType.CENTER_CROP }
        val check = ui.icon(R.drawable.ic_check_circle, 22, palette.accent).apply { visibility = View.GONE }
        val name = ui.text("", 15f).apply { maxLines = 1; ellipsize = TextUtils.TruncateAt.MIDDLE }
        val sub = ui.muted("", 12f).apply { maxLines = 1; ellipsize = TextUtils.TruncateAt.END }
        val kept = ui.icon(R.drawable.ic_offline, 14, palette.mute).apply { visibility = View.GONE }
        val star = ui.iconOnly(R.drawable.ic_star_outline, "Favorite", palette.mute) {}

        init {
            thumbBox.addView(badge)
            thumbBox.addView(folderIcon, FrameLayout.LayoutParams(ui.dp(26), ui.dp(26), Gravity.CENTER))
            thumbBox.addView(image, FrameLayout.LayoutParams(ui.dp(44), ui.dp(44)))
            thumbBox.addView(check, FrameLayout.LayoutParams(ui.dp(22), ui.dp(22), Gravity.TOP or Gravity.START))
            root.addView(thumbBox, LinearLayout.LayoutParams(ui.dp(44), ui.dp(44)))
            val texts = ui.vertical().apply {
                setPadding(ui.dp(14), 0, ui.dp(4), 0)
                addView(name)
                addView(
                    ui.horizontal().apply {
                        addView(sub)
                        addView(kept, LinearLayout.LayoutParams(ui.dp(14), ui.dp(14)).apply { leftMargin = ui.dp(6) })
                    },
                )
            }
            root.addView(texts, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
            root.addView(star)
        }
    }

    private inner class Adapter : RecyclerView.Adapter<Holder>() {
        override fun getItemCount() = folders.size + files.size

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): Holder {
            val row = ui.horizontal().apply {
                setPadding(ui.dp(16), ui.dp(8), ui.dp(4), ui.dp(8))
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
                holder.badge.visibility = View.GONE
                holder.folderIcon.visibility = View.VISIBLE
                holder.kept.visibility = View.GONE
                holder.image.tag = null
                holder.image.setImageDrawable(null)
                holder.star.visibility = View.INVISIBLE
                val picked = folder.id in selFolders
                holder.check.visibility = if (picked) View.VISIBLE else View.GONE
                holder.root.setBackgroundColor(if (picked) palette.line else Color.TRANSPARENT)
                holder.root.setOnClickListener {
                    if (selecting) {
                        toggle(selFolders, folder.id)
                    } else {
                        trail.add(Crumb(folder.id, folder.name))
                        reload()
                    }
                }
                holder.root.setOnLongClickListener {
                    it.performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
                    startSelection()
                    toggle(selFolders, folder.id)
                    true
                }
                return
            }
            val index = position - folders.size
            val file = files[index]
            holder.name.text = file.name
            holder.sub.text = "${fmtBytes(file.size)}  |  ${fmtDate(file.displayMillis)}"
            holder.kept.visibility = if (OfflineStore.has(host.ui.context, file.id)) View.VISIBLE else View.GONE
            holder.folderIcon.visibility = View.GONE
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
            holder.star.visibility = View.VISIBLE
            holder.star.setImageResource(if (file.favorite) R.drawable.ic_star else R.drawable.ic_star_outline)
            holder.star.imageTintList = android.content.res.ColorStateList.valueOf(if (file.favorite) palette.ink else palette.mute)
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
            val picked = file.id in selFiles
            holder.check.visibility = if (picked) View.VISIBLE else View.GONE
            holder.root.setBackgroundColor(if (picked) palette.line else Color.TRANSPARENT)
            holder.root.setOnClickListener {
                if (selecting) toggle(selFiles, file.id) else host.openViewer(files.toList(), index)
            }
            holder.root.setOnLongClickListener {
                it.performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
                startSelection()
                toggle(selFiles, file.id)
                true
            }
        }
    }
}
