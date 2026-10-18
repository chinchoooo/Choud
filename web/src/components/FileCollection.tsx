import { useState, type ReactNode } from "react";

import { formatBytes, formatDateTime } from "../lib/format";
import type { FileResponse, FolderResponse } from "../types/files";
import { RowMenu, type MenuItem } from "./RowMenu";
import { FolderBadge, Thumb } from "./Thumb";

export type ViewMode = "list" | "grid";

const VIEW_KEY = "personal_cloud_view";

export function loadViewMode(): ViewMode {
  try {
    return localStorage.getItem(VIEW_KEY) === "grid" ? "grid" : "list";
  } catch {
    return "list";
  }
}

export function saveViewMode(mode: ViewMode): void {
  try {
    localStorage.setItem(VIEW_KEY, mode);
  } catch {
    // not persisted
  }
}

export function ViewToggle({ mode, onChange }: { mode: ViewMode; onChange: (mode: ViewMode) => void }) {
  const base = "px-3 py-1.5 text-sm border border-gray-300";
  const active = "bg-gray-900 text-white";
  const inactive = "bg-white text-gray-700 hover:bg-gray-100";
  return (
    <div role="group" aria-label="View" className="inline-flex">
      <button
        onClick={() => onChange("list")}
        aria-pressed={mode === "list"}
        className={`${base} rounded-l-md ${mode === "list" ? active : inactive}`}
      >
        List
      </button>
      <button
        onClick={() => onChange("grid")}
        aria-pressed={mode === "grid"}
        className={`${base} -ml-px rounded-r-md ${mode === "grid" ? active : inactive}`}
      >
        Grid
      </button>
    </div>
  );
}

interface Props {
  folders?: FolderResponse[];
  files: FileResponse[];
  mode: ViewMode;
  /** Shown under the name in list view, e.g. the folder path on the Favorites page. */
  showPath?: boolean;
  empty: ReactNode;
  onOpenFolder?: (folder: FolderResponse) => void;
  onOpenFile: (index: number) => void;
  onToggleFavorite: (file: FileResponse) => void;
  onDownload: (file: FileResponse) => void;
  fileMenu: (file: FileResponse) => MenuItem[];
  folderMenu?: (folder: FolderResponse) => MenuItem[];
  /** When set, every row gets a checkbox (bulk actions). */
  selection?: {
    files: ReadonlySet<string>;
    folders: ReadonlySet<string>;
    toggleFile: (id: string) => void;
    toggleFolder: (id: string) => void;
  };
  /** Rendered under a file's row (the inline version history). */
  expandedFor?: string | null;
  renderExpanded?: (file: FileResponse) => ReactNode;
}

function Check({
  checked,
  label,
  onChange,
  className = "",
}: {
  checked: boolean;
  label: string;
  onChange: () => void;
  className?: string;
}) {
  return (
    <input
      type="checkbox"
      checked={checked}
      onChange={onChange}
      aria-label={label}
      className={`h-4 w-4 shrink-0 accent-gray-900 ${className}`}
    />
  );
}

function Star({ file, onToggle }: { file: FileResponse; onToggle: (file: FileResponse) => void }) {
  return (
    <button
      onClick={(event) => {
        event.stopPropagation();
        onToggle(file);
      }}
      aria-pressed={!!file.is_favorite}
      aria-label={file.is_favorite ? `Remove ${file.name} from favorites` : `Add ${file.name} to favorites`}
      className={`px-1.5 py-1 text-base ${file.is_favorite ? "text-amber-500" : "text-gray-400 hover:text-gray-700"}`}
    >
      {file.is_favorite ? "★" : "☆"}
    </button>
  );
}

/** Folders and files as a list or a thumbnail grid. Used by Files, Favorites and Recent. */
export function FileCollection({
  folders = [],
  files,
  mode,
  showPath = false,
  empty,
  onOpenFolder,
  onOpenFile,
  onToggleFavorite,
  onDownload,
  fileMenu,
  folderMenu,
  selection,
  expandedFor,
  renderExpanded,
}: Props) {
  const [hovered, setHovered] = useState<string | null>(null);

  if (folders.length === 0 && files.length === 0) {
    return <div className="border border-gray-200 bg-white p-6 text-sm text-gray-500 rounded-lg">{empty}</div>;
  }

  if (mode === "grid") {
    return (
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
        {folders.map((folder) => (
          <div
            key={folder.id}
            className="group relative flex flex-col border border-gray-200 bg-white rounded-lg"
          >
            <button
              onClick={() => onOpenFolder?.(folder)}
              className="flex aspect-square items-center justify-center text-left"
              aria-label={`Open folder ${folder.name}`}
            >
              <FolderBadge className="h-16 w-16 text-sm" />
            </button>
            {selection && (
              <Check
                checked={selection.folders.has(folder.id)}
                label={`Select folder ${folder.name}`}
                onChange={() => selection.toggleFolder(folder.id)}
                className="absolute left-1 top-1"
              />
            )}
            <div className="flex items-center justify-between gap-1 border-t border-gray-100 px-2 py-1.5">
              <span className="truncate text-sm font-medium text-gray-900" title={folder.name}>
                {folder.name}
              </span>
              {folderMenu && <RowMenu label={`Actions for folder ${folder.name}`} items={folderMenu(folder)} />}
            </div>
          </div>
        ))}
        {files.map((file, index) => (
          <div key={file.id} className="group relative flex flex-col border border-gray-200 bg-white rounded-lg">
            <button
              onClick={() => onOpenFile(index)}
              className="relative block aspect-square w-full overflow-hidden bg-gray-100"
              aria-label={`Open ${file.name}`}
            >
              <Thumb file={file} size={256} className="h-full w-full text-sm" />
            </button>
            {selection && (
              <Check
                checked={selection.files.has(file.id)}
                label={`Select ${file.name}`}
                onChange={() => selection.toggleFile(file.id)}
                className="absolute left-1 top-1"
              />
            )}
            <div className="absolute right-1 top-1 bg-white/80 rounded-md">
              <Star file={file} onToggle={onToggleFavorite} />
            </div>
            <div className="flex items-center justify-between gap-1 border-t border-gray-100 px-2 py-1.5">
              <div className="min-w-0">
                <div className="truncate text-sm text-gray-900" title={file.name}>
                  {file.name}
                </div>
                <div className="text-xs text-gray-500">{formatBytes(file.size)}</div>
              </div>
              <RowMenu label={`Actions for ${file.name}`} items={fileMenu(file)} />
            </div>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="border border-gray-200 bg-white rounded-lg">
      {folders.map((folder) => (
        <div
          key={folder.id}
          className="flex items-center gap-3 border-b border-gray-100 px-3 py-2 last:border-b-0 hover:bg-gray-50"
        >
          {selection && (
            <Check
              checked={selection.folders.has(folder.id)}
              label={`Select folder ${folder.name}`}
              onChange={() => selection.toggleFolder(folder.id)}
            />
          )}
          <FolderBadge className="h-10 w-10 shrink-0" />
          <button
            onClick={() => onOpenFolder?.(folder)}
            className="min-w-0 flex-1 truncate text-left text-sm font-medium text-gray-900 hover:underline"
          >
            {folder.name}
          </button>
          <span className="hidden text-xs text-gray-400 sm:inline">{formatDateTime(folder.updated_at)}</span>
          {folderMenu && <RowMenu label={`Actions for folder ${folder.name}`} items={folderMenu(folder)} />}
        </div>
      ))}

      {files.map((file, index) => (
        <div
          key={file.id}
          className="border-b border-gray-100 last:border-b-0"
          onMouseEnter={() => setHovered(file.id)}
          onMouseLeave={() => setHovered(null)}
        >
          <div className={`flex items-center gap-3 px-3 py-2 ${hovered === file.id ? "bg-gray-50" : ""}`}>
            {selection && (
              <Check
                checked={selection.files.has(file.id)}
                label={`Select ${file.name}`}
                onChange={() => selection.toggleFile(file.id)}
              />
            )}
            <Thumb file={file} size={128} className="h-10 w-10 shrink-0 text-[10px]" />
            <button onClick={() => onOpenFile(index)} className="min-w-0 flex-1 text-left" aria-label={`Open ${file.name}`}>
              <div className="truncate text-sm text-gray-900 hover:underline" title={file.name}>
                {file.name}
              </div>
              {showPath && (
                <div className="truncate text-xs text-gray-500">{file.folder_path ? file.folder_path : "My files"}</div>
              )}
            </button>
            <span className="hidden w-20 shrink-0 text-right text-xs text-gray-500 sm:inline">
              {formatBytes(file.size)}
            </span>
            <span className="hidden w-40 shrink-0 text-right text-xs text-gray-400 md:inline">
              {formatDateTime(file.updated_at)}
            </span>
            <Star file={file} onToggle={onToggleFavorite} />
            <button
              onClick={() => onDownload(file)}
              className="hidden px-2 py-1 text-xs text-gray-600 hover:underline sm:inline"
            >
              Download
            </button>
            <RowMenu label={`Actions for ${file.name}`} items={fileMenu(file)} />
          </div>
          {expandedFor === file.id && renderExpanded?.(file)}
        </div>
      ))}
    </div>
  );
}
