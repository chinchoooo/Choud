import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { ApiError } from "../api/client";
import { listTrash, purgeFromTrash, restoreFromTrash } from "../api/trash";
import { formatBytes, formatDateTime } from "../lib/format";
import type { TrashedFileResponse } from "../types/trash";

function reportError(err: unknown, fallback: string): void {
  window.alert(err instanceof ApiError ? err.message : fallback);
}

// Deleted files live here until they're restored or permanently deleted;
// nothing expires automatically.
export function Trash() {
  const queryClient = useQueryClient();

  const trashQuery = useQuery({ queryKey: ["trash"], queryFn: listTrash });

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ["trash"] });
    // A restored file reappears in listings and search.
    void queryClient.invalidateQueries({ queryKey: ["directory"] });
    void queryClient.invalidateQueries({ queryKey: ["search"] });
  }

  const restoreMutation = useMutation({
    mutationFn: (file: TrashedFileResponse) => restoreFromTrash(file.id),
    onSuccess: (restored, file) => {
      refresh();
      if (restored.name !== file.name) {
        window.alert(`"${file.name}" was restored as "${restored.name}" because that name was taken.`);
      }
    },
    onError: (err) => reportError(err, "Could not restore that file."),
  });

  const purgeMutation = useMutation({
    mutationFn: (file: TrashedFileResponse) => purgeFromTrash(file.id),
    onSuccess: refresh,
    onError: (err) => reportError(err, "Could not permanently delete that file."),
  });

  function handlePurge(file: TrashedFileResponse) {
    const ok = window.confirm(
      `Permanently delete "${file.name}" and all of its versions? This cannot be undone.`,
    );
    if (!ok) return;
    purgeMutation.mutate(file);
  }

  const files = trashQuery.data?.files ?? [];

  return (
    <div className="mx-auto max-w-4xl p-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Trash</h1>
          <p className="mt-1 text-sm text-gray-500">
            Deleted files stay here until you restore or permanently delete them.
          </p>
        </div>
        <Link
          to="/files"
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
        >
          Back to files
        </Link>
      </div>

      <div className="mt-6 overflow-hidden rounded-lg border border-gray-200">
        {trashQuery.isLoading && <p className="p-4 text-sm text-gray-500">Loading…</p>}
        {trashQuery.isError && (
          <p className="p-4 text-sm text-red-600">Could not load the trash.</p>
        )}
        {!trashQuery.isLoading && !trashQuery.isError && files.length === 0 && (
          <p className="p-4 text-sm text-gray-500">The trash is empty.</p>
        )}

        {files.map((file) => (
          <div
            key={file.id}
            className="flex items-center justify-between border-b border-gray-100 px-4 py-3 last:border-b-0"
          >
            <span className="flex-1 truncate text-sm text-gray-900">📄 {file.name}</span>
            <span className="mr-3 hidden text-xs text-gray-400 sm:inline">
              {formatBytes(file.size)} · deleted {formatDateTime(file.deleted_at)}
            </span>
            <div className="flex shrink-0 gap-2 text-xs">
              <button
                onClick={() => restoreMutation.mutate(file)}
                disabled={restoreMutation.isPending}
                className="text-gray-600 hover:underline disabled:opacity-50"
              >
                Restore
              </button>
              <button
                onClick={() => handlePurge(file)}
                disabled={purgeMutation.isPending}
                className="text-red-600 hover:underline disabled:opacity-50"
              >
                Delete forever
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
