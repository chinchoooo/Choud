import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

import { listDirectory } from "../api/files";
import { getFolder } from "../api/folders";
import type { FolderResponse } from "../types/files";

/** A centred modal. Esc and a click on the backdrop close it; focus moves inside. */
export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
      }
    }
    window.addEventListener("keydown", onKey);
    ref.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className="w-full max-w-md border border-gray-300 bg-white p-5 shadow-xl outline-none rounded-lg"
      >
        <h2 className="text-base font-semibold text-gray-900">{title}</h2>
        <div className="mt-3">{children}</div>
      </div>
    </div>
  );
}

const buttonBase = "px-3 py-1.5 text-sm border rounded-md disabled:opacity-50";
export const primaryButton = `${buttonBase} border-gray-900 bg-gray-900 text-white hover:opacity-90`;
export const plainButton = `${buttonBase} border-gray-300 text-gray-700 hover:bg-gray-100`;

export function PromptDialog({
  title,
  label,
  initial = "",
  confirmLabel = "OK",
  onSubmit,
  onClose,
}: {
  title: string;
  label: string;
  initial?: string;
  confirmLabel?: string;
  onSubmit: (value: string) => void;
  onClose: () => void;
}) {
  const [value, setValue] = useState(initial);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    input.current?.focus();
    input.current?.select();
  }, []);

  function handle(event: FormEvent) {
    event.preventDefault();
    const trimmed = value.trim();
    if (!trimmed) return;
    onSubmit(trimmed);
  }

  return (
    <Modal title={title} onClose={onClose}>
      <form onSubmit={handle}>
        <label className="block text-sm text-gray-700">
          {label}
          <input
            ref={input}
            value={value}
            onChange={(event) => setValue(event.target.value)}
            className="mt-1 w-full border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 rounded-md"
          />
        </label>
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" onClick={onClose} className={plainButton}>
            Cancel
          </button>
          <button type="submit" disabled={!value.trim()} className={primaryButton}>
            {confirmLabel}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function ConfirmDialog({
  title,
  message,
  confirmLabel,
  danger = false,
  onConfirm,
  onClose,
}: {
  title: string;
  message: string;
  confirmLabel: string;
  danger?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  return (
    <Modal title={title} onClose={onClose}>
      <p className="text-sm text-gray-700">{message}</p>
      <div className="mt-4 flex justify-end gap-2">
        <button onClick={onClose} className={plainButton}>
          Cancel
        </button>
        <button
          onClick={onConfirm}
          className={danger ? `${buttonBase} border-red-600 bg-red-600 text-white hover:opacity-90` : primaryButton}
        >
          {confirmLabel}
        </button>
      </div>
    </Modal>
  );
}

/** Pick a destination folder by browsing; "Move here" confirms the folder being shown. */
export function FolderPicker({
  title,
  excludeFolderId,
  onPick,
  onClose,
}: {
  title: string;
  /** A folder that cannot be chosen (the one being moved, so it can't move into itself). */
  excludeFolderId?: string;
  onPick: (folderId: string | null) => void;
  onClose: () => void;
}) {
  const [current, setCurrent] = useState<string | null>(null);

  const listing = useQuery({ queryKey: ["picker", current], queryFn: () => listDirectory(current) });
  const trail = useQuery({
    queryKey: ["picker-trail", current],
    queryFn: async () => {
      const names: FolderResponse[] = [];
      let id: string | null = current;
      while (id && names.length < 32) {
        const folder = await getFolder(id);
        names.unshift(folder);
        id = folder.parent_id;
      }
      return names;
    },
  });

  const folders = (listing.data?.subfolders ?? []).filter((folder) => folder.id !== excludeFolderId);

  return (
    <Modal title={title} onClose={onClose}>
      <nav className="mb-2 flex flex-wrap items-center gap-1 text-xs text-gray-500">
        <button onClick={() => setCurrent(null)} className="hover:underline">
          My files
        </button>
        {(trail.data ?? []).map((folder) => (
          <span key={folder.id} className="flex items-center gap-1">
            / <button onClick={() => setCurrent(folder.id)} className="hover:underline">{folder.name}</button>
          </span>
        ))}
      </nav>
      <ul className="max-h-60 overflow-y-auto border border-gray-200">
        {listing.isLoading && <li className="p-3 text-sm text-gray-500">Loading…</li>}
        {!listing.isLoading && folders.length === 0 && (
          <li className="p-3 text-sm text-gray-500">No folders here.</li>
        )}
        {folders.map((folder) => (
          <li key={folder.id} className="border-b border-gray-100 last:border-b-0">
            <button
              onClick={() => setCurrent(folder.id)}
              className="w-full px-3 py-2 text-left text-sm text-gray-900 hover:bg-gray-100"
            >
              {folder.name}
            </button>
          </li>
        ))}
      </ul>
      <div className="mt-4 flex justify-end gap-2">
        <button onClick={onClose} className={plainButton}>
          Cancel
        </button>
        <button onClick={() => onPick(current)} className={primaryButton}>
          Move here
        </button>
      </div>
    </Modal>
  );
}
