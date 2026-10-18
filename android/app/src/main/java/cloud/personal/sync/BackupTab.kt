package cloud.personal.sync

import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.work.WorkManager

/**
 * The upload queue: what is happening now, what is next, what just finished, with an
 * overall bar, the speed and the time left. Everything updates live.
 */
class BackupTab(private val host: Host) : Tab {
    private val ui = host.ui
    private val palette = ui.palette

    private val titleView = ui.text("", 20f, bold = true)
    private val tileDone = ui.text("0", 22f, bold = true)
    private val tileWaiting = ui.text("0", 22f, bold = true)
    private val tileFailed = ui.text("0", 22f, bold = true)
    private val subtitleView = ui.muted("", 13f)
    private val problemView = ui.text("", 13f, palette.danger)
    private val overallBar = ui.bar()
    private val overallText = ui.muted("", 12f)
    private val filesText = ui.muted("", 12f)
    private val jobView = ui.muted("", 12f)

    private val nowBox = ui.vertical()
    private val nextBox = ui.vertical()
    private val doneBox = ui.vertical()
    private val failuresBox = ui.vertical()

    private val startButton = ui.button("Back up now", primary = true) {
        host.requestMediaPermissions()
        EventLog.log("user: Back up now")
        SyncWorker.runNow(host.ui.context)
    }
    private val stopButton = ui.button("Stop") {
        EventLog.log("user: Stop")
        LiveStatus.cancelRequested = true
        LiveStatus.phase = "stopping"
        WorkManager.getInstance(host.ui.context).cancelUniqueWork(SyncWorker.ONCE)
    }
    private val retryButton = ui.button("Retry failed files") {
        val db = BackupDb(host.ui.context)
        val n = db.resetFailed()
        db.close()
        EventLog.log("user: retry $n failed file(s)")
        SyncWorker.runNow(host.ui.context)
    }

    // Speed: sampled on every tick and smoothed, so the number is steady but still reacts.
    private var lastSampleAt = 0L
    private var lastSampleBytes = 0L
    private var speed = 0.0
    private var runStartedAt = 0L

    private val activeRows = LinkedHashMap<String, ActiveRow>()
    // null = nothing drawn yet, so the first render always happens (even when the list is empty)
    private var nextSignature: String? = null
    private var doneSignature: String? = null
    private var failuresSignature: String? = null
    private var nowSignature: List<String>? = null

    private class ActiveRow(
        val container: LinearLayout,
        val name: TextView,
        val phase: TextView,
        val bar: ProgressBarView,
        val bytes: TextView,
    )

    override val view: View = ScrollView(ui.context).apply {
        val column = ui.vertical().apply { setPadding(ui.dp(14), ui.dp(12), ui.dp(14), ui.dp(24)) }

        fun tile(value: TextView, label: String): LinearLayout = ui.vertical().apply {
            setPadding(ui.dp(12), ui.dp(10), ui.dp(12), ui.dp(10))
            background = ui.box(palette.surface, palette.line)
            addView(value)
            addView(ui.muted(if (palette.retro) label.uppercase() else label, 11f))
        }
        val summary = ui.card().apply {
            setPadding(ui.dp(16), ui.dp(16), ui.dp(16), ui.dp(14))
            addView(
                ui.horizontal().apply {
                    addView(ui.icon(R.drawable.ic_nav_backup, 26, palette.ink))
                    addView(titleView, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { leftMargin = ui.dp(12) })
                },
            )
            addView(subtitleView, ui.matchWidth(4))
            addView(
                ui.horizontal().apply {
                    addView(tile(tileDone, "Backed up"), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
                    addView(View(ui.context), LinearLayout.LayoutParams(ui.dp(8), 1))
                    addView(tile(tileWaiting, "Waiting"), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
                    addView(View(ui.context), LinearLayout.LayoutParams(ui.dp(8), 1))
                    addView(tile(tileFailed, "Failed"), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
                },
                ui.matchWidth(14),
            )
            addView(overallBar, ui.matchWidth(14))
            addView(overallText, ui.matchWidth(6))
            addView(filesText, ui.matchWidth(0))
            addView(problemView, ui.matchWidth(6))
            addView(jobView, ui.matchWidth(2))
        }
        column.addView(summary, ui.matchWidth())

        val buttons = ui.horizontal().apply {
            addView(startButton, LinearLayout.LayoutParams(0, ui.dp(50), 1f))
            addView(stopButton, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ui.dp(50)).apply { leftMargin = ui.dp(8) })
            addView(retryButton, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ui.dp(50)).apply { leftMargin = ui.dp(8) })
        }
        column.addView(buttons, ui.matchWidth(12))

        column.addView(section("Uploading now"), ui.matchWidth(18))
        column.addView(nowBox, ui.matchWidth(6))
        column.addView(section("Up next"), ui.matchWidth(18))
        column.addView(nextBox, ui.matchWidth(6))
        column.addView(section("Recently finished"), ui.matchWidth(18))
        column.addView(doneBox, ui.matchWidth(6))
        column.addView(failuresBox, ui.matchWidth(10))
        addView(column)
        setBackgroundColor(palette.bg)
    }

    private fun section(title: String): TextView =
        ui.text(if (palette.retro) title.uppercase() else title, 12f, palette.mute, bold = true).apply { letterSpacing = 0.04f }

    override fun onShow() = onTick()

    override fun onTick() {
        val facts = host.facts
        val now = System.currentTimeMillis()
        val running = LiveStatus.running

        // ---- speed -------------------------------------------------------------
        if (running) {
            if (runStartedAt != LiveStatus.runStartedMillis) {
                runStartedAt = LiveStatus.runStartedMillis
                lastSampleAt = 0
                speed = 0.0
            }
            val bytes = LiveStatus.bytesNow()
            if (lastSampleAt != 0L && now - lastSampleAt >= 400) {
                val instantaneous = ((bytes - lastSampleBytes).coerceAtLeast(0)) * 1000.0 / (now - lastSampleAt)
                speed = smoothSpeed(speed, instantaneous)
            }
            if (lastSampleAt == 0L || now - lastSampleAt >= 400) {
                lastSampleAt = now
                lastSampleBytes = bytes
            }
        } else {
            lastSampleAt = 0
            speed = 0.0
        }

        // ---- summary -----------------------------------------------------------
        val total = LiveStatus.total
        val done = LiveStatus.done.get()
        val failed = LiveStatus.failed.get()
        val waiting = LiveStatus.waiting.size
        if (running && LiveStatus.phase == "dates") {
            val total = LiveStatus.datesTotal
            val doneDates = LiveStatus.datesDone.get()
            titleView.text = "Fixing file dates"
            subtitleView.text = "Putting your phone's real dates on files that were backed up earlier"
            overallBar.progress = if (total > 0) doneDates.toFloat() / total else 0f
            overallText.text = "$doneDates of $total files"
            filesText.text = "Dates only; nothing is uploaded again."
        } else if (running) {
            if (LiveStatus.phase == "scanning") {
                titleView.text = "Looking for new photos..."
                subtitleView.text = "Checking your camera roll"
            } else {
                titleView.text = if (LiveStatus.phase == "stopping") "Stopping..." else "Backing up"
                subtitleView.text = "$done done  |  ${LiveStatus.active.size} in progress  |  $waiting waiting  |  $failed failed"
            }
            val doneBytes = LiveStatus.bytesNow()
            val totalBytes = LiveStatus.bytesTotalAll
            overallBar.progress = if (totalBytes > 0) doneBytes.toFloat() / totalBytes else 0f
            val eta = etaSeconds(totalBytes - doneBytes, speed)
            overallText.text = "${fmtBytes(doneBytes)} of ${fmtBytes(totalBytes)}   |   ${fmtSpeed(speed)}   |   " +
                (if (eta == null) "time left: calculating" else "${fmtDuration(eta)} left")
            val elapsed = (now - LiveStatus.runStartedMillis) / 1000
            filesText.text = "File ${minOf(done + failed + LiveStatus.active.size, total)} of $total   |   running for ${fmtDuration(elapsed)}"
        } else {
            val pending = facts.pending
            titleView.text = when {
                pending > 0 -> "$pending photo${if (pending == 1) "" else "s"} waiting"
                facts.visible == 0 -> "No photos found"
                else -> "All caught up"
            }
            subtitleView.text = "${facts.done} backed up  |  ${facts.failed} failed  |  ${facts.visible} on this phone"
            overallBar.progress = if (facts.visible > 0) facts.done.toFloat() / facts.visible else 0f
            overallText.text = "Last run: ${facts.lastRun}"
            filesText.text = when {
                pending > 0 -> "Tap Back up now, or wait for the next scheduled run (Wi-Fi + charging)."
                facts.datesPending > 0 -> "${facts.datesPending} backed-up files still need their real dates: tap Back up now."
                else -> ""
            }
        }
        tileDone.text = (if (running) done else facts.done).toString()
        tileWaiting.text = (if (running) waiting + LiveStatus.active.size else facts.pending).toString()
        tileFailed.text = (if (running) failed else facts.failed).toString()
        problemView.visibility = if (facts.lastError.isNotEmpty() && !running) View.VISIBLE else View.GONE
        problemView.text = if (facts.lastError.isNotEmpty()) "Problem: ${facts.lastError}" else ""
        jobView.text = if (!running && facts.jobNow.isNotEmpty()) "Job: ${facts.jobNow}" else ""
        jobView.visibility = if (jobView.text.isEmpty()) View.GONE else View.VISIBLE

        startButton.isEnabled = !running
        startButton.alpha = if (running) 0.5f else 1f
        stopButton.visibility = if (running && LiveStatus.phase != "stopping") View.VISIBLE else View.GONE
        retryButton.visibility = if (!running && facts.failed > 0) View.VISIBLE else View.GONE

        renderActive()
        renderNext(waiting)
        renderDone()
        renderFailures(facts)
    }

    private fun phaseText(phase: String) = when (phase) {
        "hashing" -> "Checking integrity"
        "uploading" -> "Uploading"
        "preparing" -> "Preparing"
        "checking" -> "Comparing with the copy on the server"
        else -> phase.replaceFirstChar { it.uppercase() }
    }

    private fun renderActive() {
        val current = LiveStatus.active.values.sortedBy { it.startedAt }
        val keys = current.map { it.key }
        if (keys != nowSignature) {
            nowSignature = keys
            nowBox.removeAllViews()
            activeRows.clear()
            if (current.isEmpty()) {
                nowBox.addView(ui.muted(if (LiveStatus.running) "Starting..." else "Nothing is uploading."), ui.matchWidth())
            }
            for (item in current) {
                val container = ui.card()
                val name = ui.text(item.name, 14f).apply { maxLines = 1; ellipsize = android.text.TextUtils.TruncateAt.MIDDLE }
                val phase = ui.muted("", 12f)
                val bar = ui.bar()
                val bytes = ui.muted("", 12f)
                container.addView(name)
                container.addView(phase, ui.matchWidth(2))
                container.addView(bar, ui.matchWidth(8))
                container.addView(bytes, ui.matchWidth(4))
                nowBox.addView(container, ui.matchWidth(if (activeRows.isEmpty()) 0 else 8))
                activeRows[item.key] = ActiveRow(container, name, phase, bar, bytes)
            }
        }
        for (item in current) {
            val row = activeRows[item.key] ?: continue
            val fraction = if (item.size > 0) item.bytes.toFloat() / item.size else 0f
            row.phase.text = phaseText(item.phase)
            row.bar.progress = if (item.phase == "uploading" || item.phase == "hashing") fraction else 0f
            row.bytes.text = if (item.phase == "uploading" || item.phase == "hashing") {
                "${fmtBytes(item.bytes)} of ${fmtBytes(item.size)}  (${(fraction * 100).toInt()}%)"
            } else {
                fmtBytes(item.size)
            }
        }
    }

    private fun renderNext(waitingCount: Int) {
        val upcoming = LiveStatus.waiting.toList().take(8)
        val signature = "$waitingCount|" + upcoming.joinToString("|") { it.name }
        if (signature == nextSignature) return
        nextSignature = signature
        nextBox.removeAllViews()
        if (upcoming.isEmpty()) {
            nextBox.addView(ui.muted("Nothing is waiting."), ui.matchWidth())
            return
        }
        upcoming.forEachIndexed { i, entry ->
            val row = ui.horizontal().apply {
                setPadding(0, ui.dp(5), 0, ui.dp(5))
                addView(ui.muted("${i + 1}.", 12f).apply { minWidth = ui.dp(24) })
                addView(
                    ui.text(entry.name, 13f).apply { maxLines = 1; ellipsize = android.text.TextUtils.TruncateAt.MIDDLE },
                    LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f),
                )
                addView(ui.muted(fmtBytes(entry.size), 12f))
            }
            nextBox.addView(row, ui.matchWidth())
            if (i < upcoming.lastIndex) nextBox.addView(ui.divider())
        }
        if (waitingCount > upcoming.size) {
            nextBox.addView(ui.muted("...and ${waitingCount - upcoming.size} more", 12f), ui.matchWidth(6))
        }
    }

    private fun renderDone() {
        val recent = LiveStatus.recent().take(10)
        val signature = recent.joinToString("|") { "${it.name}:${it.ok}:${it.note}" }
        if (signature == doneSignature) return
        doneSignature = signature
        doneBox.removeAllViews()
        if (recent.isEmpty()) {
            doneBox.addView(ui.muted("Nothing finished yet."), ui.matchWidth())
            return
        }
        recent.forEachIndexed { i, entry ->
            val row = ui.horizontal().apply {
                setPadding(0, ui.dp(5), 0, ui.dp(5))
                addView(ui.text(if (entry.ok) "OK" else "X", 11f, if (entry.ok) palette.ok else palette.danger, bold = true).apply { minWidth = ui.dp(26) })
                addView(
                    ui.vertical().apply {
                        addView(ui.text(entry.name, 13f).apply { maxLines = 1; ellipsize = android.text.TextUtils.TruncateAt.MIDDLE })
                        addView(ui.text(entry.note, 11f, if (entry.ok) palette.mute else palette.danger))
                    },
                    LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f),
                )
                addView(ui.muted(fmtBytes(entry.size), 12f))
            }
            doneBox.addView(row, ui.matchWidth())
            if (i < recent.lastIndex) doneBox.addView(ui.divider())
        }
    }

    private fun renderFailures(facts: Facts) {
        val signature = facts.failures.joinToString("|")
        if (signature == failuresSignature) return
        failuresSignature = signature
        failuresBox.removeAllViews()
        if (facts.failures.isEmpty()) return
        failuresBox.addView(section("Files that failed (from earlier runs)"), ui.matchWidth())
        facts.failures.forEach { failuresBox.addView(ui.text(it, 11f, palette.danger), ui.matchWidth(4)) }
    }
}
