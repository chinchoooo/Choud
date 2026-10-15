import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";

import { downloadFile } from "../api/files";
import { formatBytes, formatDateTime } from "../lib/format";
import { viewerKind } from "../lib/viewerKind";
import { useMedia } from "../media/MediaContext";
import type { FileResponse } from "../types/files";
import { FileBadge } from "./Thumb";

interface Props {
  files: FileResponse[];
  index: number;
  onIndexChange: (index: number) => void;
  onClose: () => void;
  onToggleFavorite?: (file: FileResponse) => void;
  onDelete?: (file: FileResponse) => void;
}

const MAX_TEXT_BYTES = 2 * 1024 * 1024;

function ImageView({ src, name }: { src: string; name: string }) {
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);

  const reset = useCallback(() => {
    setScale(1);
    setOffset({ x: 0, y: 0 });
  }, []);

  useEffect(() => {
    reset();
    setLoaded(false);
    setFailed(false);
  }, [src, reset]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "+" || event.key === "=") setScale((value) => Math.min(8, value * 1.25));
      else if (event.key === "-") setScale((value) => Math.max(1, value / 1.25));
      else if (event.key === "0") reset();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [reset]);

  function onPointerDown(event: ReactPointerEvent) {
    if (scale <= 1) return;
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
    drag.current = { x: event.clientX, y: event.clientY, ox: offset.x, oy: offset.y };
  }
  function onPointerMove(event: ReactPointerEvent) {
    const d = drag.current;
    if (!d) return;
    setOffset({ x: d.ox + event.clientX - d.x, y: d.oy + event.clientY - d.y });
  }

  if (failed) return <p className="text-sm text-gray-500">This image could not be displayed.</p>;
  return (
    <div
      className="relative flex h-full w-full items-center justify-center overflow-hidden"
      onWheel={(event) => {
        setScale((value) => Math.min(8, Math.max(1, value * (event.deltaY < 0 ? 1.15 : 1 / 1.15))));
      }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={() => (drag.current = null)}
      onDoubleClick={() => (scale > 1 ? reset() : setScale(2.5))}
      style={{ touchAction: "none", cursor: scale > 1 ? "grab" : "zoom-in" }}
    >
      {!loaded && <span className="absolute text-sm text-gray-500">Loading…</span>}
      <img
        src={src}
        alt={name}
        draggable={false}
        onLoad={() => setLoaded(true)}
        onError={() => setFailed(true)}
        className="max-h-full max-w-full select-none object-contain"
        style={{ transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})` }}
      />
      <div className="absolute bottom-3 left-1/2 flex -translate-x-1/2 gap-1 border border-gray-300 bg-white px-1 py-0.5 text-sm">
        <button aria-label="Zoom out" className="px-2" onClick={() => setScale((v) => Math.max(1, v / 1.25))}>
          −
        </button>
        <button aria-label="Reset zoom" className="px-2" onClick={reset}>
          {Math.round(scale * 100)}%
        </button>
        <button aria-label="Zoom in" className="px-2" onClick={() => setScale((v) => Math.min(8, v * 1.25))}>
          +
        </button>
      </div>
    </div>
  );
}

function TextView({ src, size }: { src: string; size: number }) {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setText(null);
    setError(false);
    // Only the first 2 MB: a huge log should not freeze the tab.
    fetch(src, { headers: size > MAX_TEXT_BYTES ? { Range: `bytes=0-${MAX_TEXT_BYTES - 1}` } : undefined })
      .then((response) => {
        if (!response.ok) throw new Error(String(response.status));
        return response.text();
      })
      .then((body) => {
        if (!cancelled) setText(body);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [src, size]);

  if (error) return <p className="text-sm text-gray-500">This file could not be loaded.</p>;
  if (text === null) return <p className="text-sm text-gray-500">Loading…</p>;
  return (
    <div className="h-full w-full overflow-auto bg-white p-4">
      {size > MAX_TEXT_BYTES && (
        <p className="mb-2 text-xs text-gray-500">Showing the first {formatBytes(MAX_TEXT_BYTES)}. Download for the rest.</p>
      )}
      {/* React escapes the text: nothing in an uploaded file can run as markup. */}
      <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-5 text-gray-900">{text}</pre>
    </div>
  );
}

export function FileViewer({ files, index, onIndexChange, onClose, onToggleFavorite, onDelete }: Props) {
  const media = useMedia();
  const file = files[index];
  const [showInfo, setShowInfo] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  const hasPrev = index > 0;
  const hasNext = index < files.length - 1;
  const go = useCallback(
    (delta: number) => {
      const next = index + delta;
      if (next >= 0 && next < files.length) onIndexChange(next);
    },
    [index, files.length, onIndexChange],
  );

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
      else if (event.key === "ArrowLeft") go(-1);
      else if (event.key === "ArrowRight") go(1);
      else if (event.key === "i") setShowInfo((value) => !value);
    }
    window.addEventListener("keydown", onKey);
    // Lock page scroll behind the viewer and move focus into it.
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    dialogRef.current?.focus();
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [go, onClose]);

  useEffect(() => setDownloadError(null), [file?.id]);

  if (!file) return null;
  const kind = viewerKind(file);
  const src = media.contentUrl(file.id);

  async function handleDownload() {
    try {
      setDownloadError(null);
      await downloadFile(file.id, file.name);
    } catch {
      setDownloadError("Download failed.");
    }
  }

  let body;
  if (!src) {
    body = <p className="text-sm text-gray-500">Loading…</p>;
  } else if (kind === "image") {
    body = <ImageView src={src} name={file.name} />;
  } else if (kind === "video") {
    // key: switching files must reload the player, not reuse the old stream.
    body = (
      <video key={file.id} src={src} controls autoPlay playsInline className="max-h-full max-w-full bg-black">
        Your browser cannot play this video.
      </video>
    );
  } else if (kind === "audio") {
    body = (
      <div className="flex flex-col items-center gap-4 p-6">
        <FileBadge file={file} className="h-24 w-24 text-lg" />
        <audio key={file.id} src={src} controls autoPlay className="w-72 max-w-full" />
      </div>
    );
  } else if (kind === "pdf") {
    body = <iframe key={file.id} src={src} title={file.name} className="h-full w-full border-0 bg-white" />;
  } else if (kind === "text") {
    body = <TextView key={file.id} src={src} size={file.size} />;
  } else {
    body = (
      <div className="flex flex-col items-center gap-3 p-6 text-center">
        <FileBadge file={file} className="h-24 w-24 text-lg" />
        <p className="text-sm text-gray-700">There is no preview for this type of file.</p>
        <button
          onClick={() => void handleDownload()}
          className="border border-gray-300 bg-gray-900 px-4 py-2 text-sm text-white hover:opacity-90"
        >
          Download {file.name}
        </button>
      </div>
    );
  }

  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-label={`Viewing ${file.name}`}
      tabIndex={-1}
      className="fixed inset-0 z-50 flex flex-col bg-gray-50 outline-none"
    >
      <header className="flex items-center gap-2 border-b border-gray-200 bg-white px-3 py-2">
        <button onClick={onClose} aria-label="Close viewer" className="px-2 py-1 text-lg text-gray-700 hover:bg-gray-100">
          ✕
        </button>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-gray-900" title={file.name}>
            {file.name}
          </div>
          <div className="text-xs text-gray-500">
            {index + 1} of {files.length} · {formatBytes(file.size)}
          </div>
        </div>
        {onToggleFavorite && (
          <button
            onClick={() => onToggleFavorite(file)}
            aria-pressed={!!file.is_favorite}
            aria-label={file.is_favorite ? "Remove from favorites" : "Add to favorites"}
            className="px-2 py-1 text-lg text-gray-700 hover:bg-gray-100"
          >
            {file.is_favorite ? "★" : "☆"}
          </button>
        )}
        <button onClick={() => void handleDownload()} className="px-2 py-1 text-sm text-gray-700 hover:bg-gray-100">
          Download
        </button>
        <button
          onClick={() => setShowInfo((value) => !value)}
          aria-pressed={showInfo}
          className="px-2 py-1 text-sm text-gray-700 hover:bg-gray-100"
        >
          Info
        </button>
        {onDelete && (
          <button onClick={() => onDelete(file)} className="px-2 py-1 text-sm text-red-600 hover:bg-gray-100">
            Delete
          </button>
        )}
      </header>

      <div className="relative flex min-h-0 flex-1">
        <main className="relative flex min-w-0 flex-1 items-center justify-center bg-gray-100">
          {hasPrev && (
            <button
              onClick={() => go(-1)}
              aria-label="Previous file"
              className="absolute left-2 top-1/2 z-10 -translate-y-1/2 border border-gray-300 bg-white px-3 py-2 text-xl text-gray-800 hover:bg-gray-100"
            >
              ‹
            </button>
          )}
          {body}
          {hasNext && (
            <button
              onClick={() => go(1)}
              aria-label="Next file"
              className="absolute right-2 top-1/2 z-10 -translate-y-1/2 border border-gray-300 bg-white px-3 py-2 text-xl text-gray-800 hover:bg-gray-100"
            >
              ›
            </button>
          )}
          {downloadError && (
            <p className="absolute bottom-2 left-2 bg-white px-2 py-1 text-xs text-red-600">{downloadError}</p>
          )}
        </main>

        {showInfo && (
          <aside className="w-64 shrink-0 overflow-y-auto border-l border-gray-200 bg-white p-4 text-sm">
            <h2 className="mb-3 text-sm font-semibold text-gray-900">Details</h2>
            <dl className="space-y-2 text-xs text-gray-700">
              <div>
                <dt className="text-gray-500">Name</dt>
                <dd className="break-words">{file.name}</dd>
              </div>
              <div>
                <dt className="text-gray-500">Type</dt>
                <dd>{file.mime_type ?? "unknown"}</dd>
              </div>
              <div>
                <dt className="text-gray-500">Size</dt>
                <dd>{formatBytes(file.size)}</dd>
              </div>
              {file.taken_at && (
                <div>
                  <dt className="text-gray-500">Taken</dt>
                  <dd>{formatDateTime(file.taken_at)}</dd>
                </div>
              )}
              <div>
                <dt className="text-gray-500">Added</dt>
                <dd>{formatDateTime(file.created_at)}</dd>
              </div>
              <div>
                <dt className="text-gray-500">Modified</dt>
                <dd>{formatDateTime(file.updated_at)}</dd>
              </div>
              <div>
                <dt className="text-gray-500">Folder</dt>
                <dd className="break-words">{file.folder_path ? file.folder_path : "My files"}</dd>
              </div>
              {file.content_hash && (
                <div>
                  <dt className="text-gray-500">SHA-256</dt>
                  <dd className="break-all font-mono">{file.content_hash}</dd>
                </div>
              )}
            </dl>
          </aside>
        )}
      </div>
    </div>
  );
}
