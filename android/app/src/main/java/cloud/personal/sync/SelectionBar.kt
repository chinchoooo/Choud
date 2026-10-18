package cloud.personal.sync

import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.TextView

/** What the selection bar can ask for. */
class SelectionActions(
    val onClose: () -> Unit,
    val onSelectAll: () -> Unit,
    val onShare: () -> Unit,
    val onDownload: () -> Unit,
    val onKeep: () -> Unit,
    val onFavorite: () -> Unit,
    val onMove: () -> Unit,
    val onDelete: () -> Unit,
    /** Shown only while exactly one item is selected. Null = this tab cannot rename. */
    val onRename: (() -> Unit)? = null,
)

/**
 * The bar that replaces a tab's header while selecting: a close button, "N selected", and one icon
 * per action. Actions that cannot apply to the current selection (sharing a folder, say) are dimmed
 * rather than hidden, so the bar never jumps around.
 */
class SelectionBar(private val ui: Ui, private val actions: SelectionActions) {
    private val count: TextView = ui.text("", 15f, bold = true)
    private val row = ui.horizontal()

    val view: View = ui.vertical().apply {
        setBackgroundColor(ui.palette.surface)
        val top = ui.horizontal().apply {
            setPadding(ui.dp(4), 0, ui.dp(12), 0)
            addView(ui.iconOnly(R.drawable.ic_close, "Cancel selection") { actions.onClose() })
            addView(count, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            addView(ui.iconOnly(R.drawable.ic_select_all, "Select all") { actions.onSelectAll() })
        }
        addView(top, ui.matchWidth())
        addView(
            HorizontalScrollView(ui.context).apply {
                isHorizontalScrollBarEnabled = false
                addView(row)
            },
            ui.matchWidth(),
        )
        addView(ui.divider())
    }

    fun update(selectedCount: Int, hasFiles: Boolean, hasFolders: Boolean, allFavorite: Boolean) {
        val canRename = actions.onRename != null && selectedCount == 1
        count.text = if (selectedCount == 0) "Select items" else "$selectedCount selected"
        row.removeAllViews()
        val any = selectedCount > 0
        row.gravity = Gravity.CENTER_VERTICAL
        row.addView(ui.iconButton(R.drawable.ic_share, "Share", enabled = any && hasFiles) { actions.onShare() })
        row.addView(ui.iconButton(R.drawable.ic_download, "Save", enabled = any) { actions.onDownload() })
        row.addView(ui.iconButton(R.drawable.ic_offline, "Offline", enabled = any && hasFiles) { actions.onKeep() })
        row.addView(
            ui.iconButton(if (allFavorite) R.drawable.ic_star else R.drawable.ic_star_outline, if (allFavorite) "Unstar" else "Star", enabled = any && hasFiles) {
                actions.onFavorite()
            },
        )
        row.addView(ui.iconButton(R.drawable.ic_move, "Move", enabled = any) { actions.onMove() })
        if (canRename) row.addView(ui.iconButton(R.drawable.ic_pencil, "Rename") { actions.onRename?.invoke() })
        row.addView(ui.iconButton(R.drawable.ic_delete, "Delete", tint = ui.palette.danger, enabled = any) { actions.onDelete() })
    }
}
