import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { listActivity, listFavorites, listRecent } from "../api/library";
import { FileCollection, ViewToggle, loadViewMode, saveViewMode, type ViewMode } from "../components/FileCollection";
import { FileViewer } from "../components/FileViewer";
import { useFileActions } from "../hooks/useFileActions";
import { formatDateTime } from "../lib/format";
import type { FileResponse } from "../types/files";

function FileListPage({
  title,
  subtitle,
  queryKey,
  load,
  emptyText,
}: {
  title: string;
  subtitle: string;
  queryKey: string;
  load: () => Promise<FileResponse[]>;
  emptyText: string;
}) {
  const query = useQuery({ queryKey: [queryKey], queryFn: load });
  const actions = useFileActions();
  const [mode, setMode] = useState<ViewMode>(loadViewMode);
  const [viewerIndex, setViewerIndex] = useState<number | null>(null);
  const files = query.data ?? [];

  return (
    <div className="mx-auto max-w-5xl p-4 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">{title}</h1>
          <p className="text-xs text-gray-500">{subtitle}</p>
        </div>
        <ViewToggle
          mode={mode}
          onChange={(next) => {
            setMode(next);
            saveViewMode(next);
          }}
        />
      </div>
      <div className="mt-4">
        {query.isLoading && <p className="p-4 text-sm text-gray-500">Loading…</p>}
        {query.isError && <p className="p-4 text-sm text-red-600">Could not load this list.</p>}
        {query.isSuccess && (
          <FileCollection
            files={files}
            mode={mode}
            showPath
            empty={emptyText}
            onOpenFile={setViewerIndex}
            onToggleFavorite={actions.toggleFavorite}
            onDownload={(file) => void actions.download(file)}
            fileMenu={actions.menuFor}
          />
        )}
      </div>
      {viewerIndex !== null && (
        <FileViewer
          files={files}
          index={Math.min(viewerIndex, Math.max(files.length - 1, 0))}
          onIndexChange={setViewerIndex}
          onClose={() => setViewerIndex(null)}
          onToggleFavorite={actions.toggleFavorite}
          onDelete={(file) => {
            setViewerIndex(null);
            actions.deleteWithConfirm(file);
          }}
        />
      )}
      {actions.dialogs}
    </div>
  );
}

export function Favorites() {
  return (
    <FileListPage
      title="Favorites"
      subtitle="Files you starred"
      queryKey="favorites"
      load={listFavorites}
      emptyText="Nothing starred yet. Use the ☆ next to a file."
    />
  );
}

export function Recent() {
  return (
    <FileListPage
      title="Recent"
      subtitle="Files you added or changed lately"
      queryKey="recent"
      load={() => listRecent(60)}
      emptyText="No files yet."
    />
  );
}

const ACTION_TEXT: Record<string, string> = {
  uploaded: "Uploaded",
  new_version: "New version of",
  renamed: "Renamed",
  moved: "Moved",
  trashed: "Moved to trash",
  restored: "Restored",
  purged: "Permanently deleted",
};

export function Activity() {
  const query = useQuery({ queryKey: ["activity"], queryFn: () => listActivity(100) });
  const items = query.data ?? [];

  return (
    <div className="mx-auto max-w-4xl p-4 sm:p-6">
      <h1 className="text-lg font-semibold text-gray-900">Activity</h1>
      <p className="text-xs text-gray-500">What happened to your files, newest first</p>
      <div className="mt-4 border border-gray-200 bg-white rounded-lg">
        {query.isLoading && <p className="p-4 text-sm text-gray-500">Loading…</p>}
        {query.isError && <p className="p-4 text-sm text-red-600">Could not load activity.</p>}
        {query.isSuccess && items.length === 0 && <p className="p-4 text-sm text-gray-500">Nothing has happened yet.</p>}
        <ul>
          {items.map((item) => (
            <li
              key={item.id}
              className="flex flex-wrap items-baseline justify-between gap-2 border-b border-gray-100 px-4 py-2.5 last:border-b-0"
            >
              <span className="min-w-0 text-sm text-gray-900">
                <span className="text-gray-500">{ACTION_TEXT[item.action] ?? item.action}</span>{" "}
                <span className="break-words font-medium">{item.file_name}</span>
                {item.detail && <span className="text-xs text-gray-500"> ({item.detail})</span>}
              </span>
              <time className="text-xs text-gray-400" dateTime={item.created_at}>
                {formatDateTime(item.created_at)}
              </time>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
