import { Download, FolderInput, Trash2, X } from "lucide-react";

import { plainButton } from "./Dialogs";

interface Props {
  count: number;
  total: number;
  busy: boolean;
  message: string | null;
  onSelectAll: () => void;
  onDownload: () => void;
  onMove: () => void;
  onTrash: () => void;
  onClear: () => void;
}

/** The action bar that appears while selecting files and folders. */
export function BulkBar({ count, total, busy, message, onSelectAll, onDownload, onMove, onTrash, onClear }: Props) {
  const none = count === 0 || busy;
  return (
    <div role="toolbar" aria-label="Bulk actions" className="mt-3 border border-gray-300 bg-gray-100 px-3 py-2 rounded-md">
      <div className="flex flex-wrap items-center gap-2">
        <span className="mr-2 text-sm font-medium text-gray-900">
          {count === 0 ? "Nothing selected" : `${count} selected`}
        </span>
        <button type="button" onClick={onSelectAll} disabled={busy || total === 0} className={plainButton}>
          {count === total && total > 0 ? "Select none" : "Select all"}
        </button>
        <button type="button" onClick={onDownload} disabled={none} className={`${plainButton} flex items-center gap-1`}>
          <Download size={14} aria-hidden /> Download .zip
        </button>
        <button type="button" onClick={onMove} disabled={none} className={`${plainButton} flex items-center gap-1`}>
          <FolderInput size={14} aria-hidden /> Move to…
        </button>
        <button type="button" onClick={onTrash} disabled={none} className={`${plainButton} flex items-center gap-1`}>
          <Trash2 size={14} aria-hidden /> Delete
        </button>
        <button type="button" onClick={onClear} className={`${plainButton} ml-auto flex items-center gap-1`}>
          <X size={14} aria-hidden /> Done
        </button>
      </div>
      {message && (
        <p role="status" className="mt-2 text-sm text-gray-700">
          {message}
        </p>
      )}
    </div>
  );
}
