package cloud.personal.sync

import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import kotlin.concurrent.thread

/**
 * The server-backed screens reachable from More: Trash, Shared links, Storage and Security.
 * Each is a full-screen page that shows what it has quickly, says when it is loading or failed, and
 * only changes things after a confirmation.
 */
class Panels(private val host: Host) {
    private val ui = host.ui
    private val palette = ui.palette

    private fun note(text: String) = ui.muted(text, 13f).apply { setPadding(ui.dp(20), ui.dp(20), ui.dp(20), ui.dp(20)) }

    private fun full() = ui.matchWidth().apply { setMargins(ui.dp(16), 0, ui.dp(16), 0) }

    /** Opens a page whose body is filled by `load` on a background thread. */
    private fun page(title: String, load: (Page) -> View) {
        val page = host.sheets.page(title)
        page.body.addView(note("Loading..."))
        thread {
            try {
                val content = load(page)
                host.runOnUi {
                    if (!page.isShowing) return@runOnUi
                    page.body.removeAllViews()
                    page.body.addView(content)
                }
            } catch (e: Exception) {
                EventLog.log("$title: ${e.javaClass.simpleName}: ${e.message}")
                host.runOnUi {
                    if (!page.isShowing) return@runOnUi
                    page.body.removeAllViews()
                    page.body.addView(note("Could not load: ${e.message}"))
                }
            }
        }
    }

    // ------------------------------------------------------------------- trash

    fun trash() = page("Trash") { page ->
        val items = host.api.trash()
        buildTrash(items, page)
    }

    private fun buildTrash(items: List<ApiClient.TrashedItem>, page: Page): View {
        val column = ui.vertical()
        if (items.isEmpty()) {
            column.addView(note("The trash is empty. Deleted files stay here until you remove them for good."))
            return column
        }
        column.addView(ui.muted("Files you delete wait here. Restore puts one back where it was.", 12f).apply {
            setPadding(ui.dp(20), ui.dp(14), ui.dp(20), ui.dp(8))
        })
        val rows = items.map { item ->
            ui.listRow(
                R.drawable.ic_trash,
                item.name,
                "${fmtBytes(item.size)}  |  deleted ${item.deletedAtMillis?.let { fmtDate(it) } ?: "recently"}",
                chevron = false,
            ) {
                host.sheets.actions(
                    item.name,
                    fmtBytes(item.size),
                    listOf(
                        SheetItem(R.drawable.ic_refresh, "Restore") { restoreOne(item, page) },
                        SheetItem(R.drawable.ic_delete, "Delete for good", "Cannot be undone", danger = true) {
                            host.sheets.confirm("Delete ${item.name} for good?", "It is removed from the server and cannot be restored.", "Delete for good", danger = true) {
                                thread {
                                    try {
                                        host.api.purge(item.id)
                                        host.runOnUi { host.toast("Deleted for good."); refresh(page) }
                                    } catch (e: Exception) {
                                        host.runOnUi { host.toast("Could not delete: ${e.message}") }
                                    }
                                }
                            }
                        },
                    ),
                )
            }
        }
        column.addView(ui.group(*rows.toTypedArray()), full())
        return column
    }

    private fun restoreOne(item: ApiClient.TrashedItem, page: Page) {
        thread {
            try {
                host.api.restoreFile(item.id)
                ListCache.clear()
                host.runOnUi { host.toast("Restored ${item.name}."); refresh(page) }
            } catch (e: Exception) {
                host.runOnUi { host.toast("Could not restore: ${e.message}") }
            }
        }
    }

    private fun refresh(page: Page) {
        thread {
            try {
                val items = host.api.trash()
                host.runOnUi {
                    if (!page.isShowing) return@runOnUi
                    page.body.removeAllViews()
                    page.body.addView(buildTrash(items, page))
                }
            } catch (_: Exception) {
            }
        }
    }

    // ----------------------------------------------------------------- shares

    fun sharedLinks() = page("Shared links") { page -> buildShares(host.api.shares(), page) }

    private fun buildShares(shares: List<ApiClient.ShareInfo>, page: Page): View {
        val column = ui.vertical()
        if (shares.isEmpty()) {
            column.addView(note("You have no links. Share a file from the viewer or by selecting photos."))
            return column
        }
        val instance = host.api.cachedInstance()
        if (instance != null && !instance.linksWorkEverywhere) {
            column.addView(
                ui.banner(
                    if (instance.publicStatus == "paused") "Public links are paused: these only open on your private network."
                    else "These links only open on your private network. Ask the administrator to run scripts/enable-public-links.sh.",
                ),
                full().apply { topMargin = ui.dp(12) },
            )
        }
        val rows = shares.map { share ->
            val details = buildString {
                append(if (share.permission == "view") "view" else share.permission)
                if (share.hasPassword) append(" | password")
                append(" | ${share.downloads} open${if (share.downloads == 1) "" else "s"}")
                share.maxDownloads?.let { append(" of $it") }
                append(" | ")
                append(share.expiresAtMillis?.let { "until ${fmtDate(it)}" } ?: "never expires")
                if (!share.active) append(" | stopped")
            }
            ui.listRow(R.drawable.ic_link, share.targetName, details, chevron = false) {
                host.sheets.actions(
                    share.targetName,
                    share.link,
                    listOf(
                        SheetItem(R.drawable.ic_copy, "Copy link") {
                            val clipboard = ui.context.getSystemService(android.content.Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager
                            clipboard.setPrimaryClip(android.content.ClipData.newPlainText("Choud link", share.link))
                            host.toast("Link copied.")
                        },
                        SheetItem(R.drawable.ic_share, "Send link") {
                            val send = android.content.Intent(android.content.Intent.ACTION_SEND).apply {
                                type = "text/plain"
                                putExtra(android.content.Intent.EXTRA_TEXT, share.link)
                            }
                            ui.context.startActivity(android.content.Intent.createChooser(send, "Send link").addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK))
                        },
                        SheetItem(R.drawable.ic_close, "Stop sharing", "The link stops working now", danger = true) {
                            thread {
                                try {
                                    host.api.revokeShare(share.id)
                                    host.runOnUi { host.toast("Link stopped."); reloadShares(page) }
                                } catch (e: Exception) {
                                    host.runOnUi { host.toast("Could not stop it: ${e.message}") }
                                }
                            }
                        },
                    ),
                )
            }
        }
        column.addView(ui.group(*rows.toTypedArray()), full().apply { topMargin = ui.dp(12) })
        column.addView(
            ui.group(
                ui.listRow(R.drawable.ic_close, "Stop all links", "Every link you made stops working", danger = true, chevron = false) {
                    host.sheets.confirm("Stop all your links?", "Everyone who has a link will see a not-found page. You can share again any time.", "Stop all", danger = true) {
                        thread {
                            try {
                                val n = host.api.revokeAllShares()
                                host.runOnUi { host.toast("Stopped $n link${if (n == 1) "" else "s"}."); reloadShares(page) }
                            } catch (e: Exception) {
                                host.runOnUi { host.toast("Could not stop them: ${e.message}") }
                            }
                        }
                    }
                },
            ),
            full().apply { topMargin = ui.dp(20) },
        )
        return column
    }

    private fun reloadShares(page: Page) {
        thread {
            try {
                val shares = host.api.shares()
                host.runOnUi {
                    if (!page.isShowing) return@runOnUi
                    page.body.removeAllViews()
                    page.body.addView(buildShares(shares, page))
                }
            } catch (_: Exception) {
            }
        }
    }

    // ----------------------------------------------------------------- storage

    fun storage() = page("Storage") { _ ->
        val space = host.api.space()
        val usage = host.api.usage()
        val column = ui.vertical()
        val bar = ui.bar().apply { progress = if (usage.quotaBytes > 0) usage.usedBytes.toFloat() / usage.quotaBytes else 0f }
        column.addView(
            ui.card().apply {
                addView(ui.text("${fmtBytes(usage.usedBytes)} of ${fmtBytes(usage.quotaBytes)}", 15f, bold = true))
                addView(bar, ui.matchWidth(10))
                addView(ui.muted("${usage.fileCount} files", 12f), ui.matchWidth(6))
            },
            full().apply { topMargin = ui.dp(16) },
        )
        column.addView(ui.sectionHeader("Where it went"))
        column.addView(
            ui.group(
                ui.listRow(title = "Your files now", value = fmtBytes(space.currentBytes), chevron = false),
                ui.listRow(title = "Saved by storing duplicates once", value = fmtBytes(space.dedupSavedBytes), chevron = false),
                ui.listRow(title = "Held only by old versions", value = fmtBytes(space.historyBytes), chevron = false),
                ui.listRow(title = "In the trash", value = fmtBytes(space.trashBytes), chevron = false),
            ),
            full(),
        )
        if (space.byType.isNotEmpty()) {
            column.addView(ui.sectionHeader("By type"))
            column.addView(
                ui.group(*space.byType.map { (name, bytes) -> ui.listRow(title = name, value = fmtBytes(bytes), chevron = false) as View }.toTypedArray()),
                full(),
            )
        }
        if (space.biggest.isNotEmpty()) {
            column.addView(ui.sectionHeader("Biggest files"))
            column.addView(
                ui.group(*space.biggest.take(8).map { (name, bytes) -> ui.listRow(title = name, value = fmtBytes(bytes), chevron = false) as View }.toTypedArray()),
                full(),
            )
        }
        column.addView(ui.spacer(24))
        column
    }

    // ---------------------------------------------------------------- security

    fun security() = page("Sign-in history") { _ ->
        val events = host.api.securityLog()
        val column = ui.vertical()
        if (events.isEmpty()) {
            column.addView(note("No sign-ins recorded yet."))
            return@page column
        }
        column.addView(ui.muted("Recent attempts on your account. Anything you do not recognise is worth a new password.", 12f).apply {
            setPadding(ui.dp(20), ui.dp(14), ui.dp(20), ui.dp(8))
        })
        val rows = events.take(40).map { e ->
            ui.listRow(
                if (e.success) R.drawable.ic_shield else R.drawable.ic_warning,
                (if (e.success) "Signed in" else "Failed attempt") + if (e.newDevice) "  (new device)" else "",
                "${e.atMillis?.let { fmtDate(it) } ?: ""}  |  ${e.ip}  |  ${e.agent.take(40)}",
                danger = !e.success,
                chevron = false,
            ) as View
        }
        column.addView(ui.group(*rows.toTypedArray()), full())
        column.addView(ui.spacer(24))
        column
    }
}
