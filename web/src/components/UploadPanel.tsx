import { useState } from "react";

import { formatBytes, formatEta, formatSpeed } from "../lib/format";
import { typeBadge } from "../lib/viewerKind";
import { useUploads, type UploadItem } from "../uploads/UploadContext";

function percent(item: UploadItem): number {
  if (item.status === "done") return 100;
  if (item.size === 0) return item.status === "uploading" ? 50 : 0;
  return Math.min(100, Math.floor((item.loaded / item.size) * 100));
}

function Bar({ value, tone }: { value: number; tone: "normal" | "error" | "done" }) {
  const fill = tone === "error" ? "bg-red-600" : tone === "done" ? "bg-green-600" : "bg-blue-600";
  return (
    <div
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={value}
      className="h-2 w-full overflow-hidden rounded-full border border-gray-300 bg-gray-100"
    >
      <div className={`h-full ${fill} transition-[width] duration-300`} style={{ width: `${value}%` }} />
    </div>
  );
}

function statusText(item: UploadItem, position: number): string {
  switch (item.status) {
    case "queued":
      return `Waiting - #${position} in line`;
    case "uploading":
      return "Uploading";
    case "retrying": {
      const seconds = item.retryAt ? Math.max(0, Math.ceil((item.retryAt - Date.now()) / 1000)) : 0;
      return `Connection problem - retry ${item.attempts} in ${seconds}s`;
    }
    case "done":
      return "Uploaded";
    case "error":
      return "Failed";
    case "cancelled":
      return "Cancelled";
  }
}

function Row({ item, position }: { item: UploadItem; position: number }) {
  const { cancel, retry } = useUploads();
  const pct = percent(item);
  const remaining = item.size - item.loaded;
  const eta = item.status === "uploading" && item.speed > 0 ? remaining / item.speed : null;
  const tone = item.status === "error" ? "error" : item.status === "done" ? "done" : "normal";
  const finished = item.status === "done" || item.status === "error" || item.status === "cancelled";

  return (
    <li className="border-b border-gray-200 px-3 py-2 last:border-b-0">
      <div className="flex items-center gap-2">
        <span className="inline-block w-10 shrink-0 border border-gray-300 text-center text-[10px] leading-5 text-gray-600">
          {typeBadge(item)}
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm text-gray-900" title={item.name}>
            {item.name}
          </div>
          <div className="truncate text-xs text-gray-500">
            {statusText(item, position)} · {item.destination}
          </div>
        </div>
        {item.status === "error" && (
          <button onClick={() => retry(item.id)} className="text-xs text-blue-600 hover:underline">
            Retry
          </button>
        )}
        {!finished && (
          <button
            onClick={() => cancel(item.id)}
            aria-label={`Cancel upload of ${item.name}`}
            className="px-1 text-sm text-gray-500 hover:text-gray-900"
          >
            ✕
          </button>
        )}
      </div>

      {item.status !== "cancelled" && (
        <div className="mt-1.5">
          <Bar value={pct} tone={tone} />
          <div className="mt-1 flex flex-wrap justify-between gap-x-3 text-xs text-gray-500">
            <span>
              {formatBytes(item.status === "done" ? item.size : item.loaded)} / {formatBytes(item.size)} · {pct}%
            </span>
            {item.status === "uploading" && (
              <span>
                {formatSpeed(item.speed)} · {formatEta(eta)} left
              </span>
            )}
          </div>
        </div>
      )}
      {item.status === "error" && item.error && <p className="mt-1 break-words text-xs text-red-600">{item.error}</p>}
    </li>
  );
}

/** The always-visible upload queue: overall progress on top, every file below, in order. */
export function UploadPanel() {
  const { items, summary, cancelAll, clearFinished } = useUploads();
  const [open, setOpen] = useState(true);

  if (items.length === 0) return null;

  const overall = summary.bytesTotal === 0 ? 0 : Math.floor((summary.bytesLoaded / summary.bytesTotal) * 100);
  const title = summary.busy
    ? `Uploading ${summary.done + 1} of ${summary.total}`
    : summary.failed > 0
      ? `${summary.done} uploaded, ${summary.failed} failed`
      : `${summary.done} uploaded`;

  // Show the queue in a meaningful order: active, then waiting (by position), then finished.
  const rank: Record<UploadItem["status"], number> = {
    uploading: 0,
    retrying: 1,
    queued: 2,
    error: 3,
    done: 4,
    cancelled: 5,
  };
  const ordered = [...items].sort((a, b) => rank[a.status] - rank[b.status]);
  const waitingIds = items.filter((item) => item.status === "queued").map((item) => item.id);

  return (
    <section
      aria-label="Upload queue"
      className="fixed inset-x-2 bottom-2 z-40 max-h-[70vh] overflow-hidden border border-gray-300 bg-white shadow-lg sm:left-auto sm:right-4 sm:bottom-4 sm:w-96 rounded-lg"
    >
      <header className="border-b border-gray-200 px-3 py-2">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-gray-900">{title}</h2>
          <div className="flex items-center gap-3 text-xs">
            {summary.busy ? (
              <button onClick={cancelAll} className="text-gray-600 hover:underline">
                Cancel all
              </button>
            ) : (
              <button onClick={clearFinished} className="text-gray-600 hover:underline">
                Clear
              </button>
            )}
            <button
              onClick={() => setOpen((value) => !value)}
              aria-expanded={open}
              className="text-gray-600 hover:underline"
            >
              {open ? "Hide" : "Show"}
            </button>
          </div>
        </div>
        <div className="mt-2">
          <Bar value={overall} tone={summary.failed > 0 && !summary.busy ? "error" : "normal"} />
          <div className="mt-1 flex flex-wrap justify-between gap-x-3 text-xs text-gray-500">
            <span>
              {formatBytes(summary.bytesLoaded)} / {formatBytes(summary.bytesTotal)} · {overall}%
            </span>
            {summary.busy && (
              <span>
                {formatSpeed(summary.speed)} · {formatEta(summary.etaSeconds)} left
              </span>
            )}
          </div>
        </div>
      </header>
      {open && (
        <ul className="max-h-[50vh] overflow-y-auto">
          {ordered.map((item) => (
            <Row key={item.id} item={item} position={waitingIds.indexOf(item.id) + 1} />
          ))}
        </ul>
      )}
    </section>
  );
}
