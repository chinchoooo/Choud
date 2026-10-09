import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError } from "../api/client";
import { downloadVersion, listVersions, restoreVersion } from "../api/versions";
import { formatBytes, formatDateTime } from "../lib/format";
import type { FileResponse } from "../types/files";
import type { VersionResponse } from "../types/versions";

function reportError(err: unknown, fallback: string): void {
  window.alert(err instanceof ApiError ? err.message : fallback);
}

interface VersionHistoryProps {
  file: FileResponse;
}

// A plain inline list of a file's versions, newest first. "Restore" does not
// rewrite history: it adds a new version that copies the old content, so the
// version you restored from (and everything after it) stays available.
export function VersionHistory({ file }: VersionHistoryProps) {
  const queryClient = useQueryClient();

  const versionsQuery = useQuery({
    queryKey: ["versions", file.id],
    queryFn: () => listVersions(file.id),
  });

  const restoreMutation = useMutation({
    mutationFn: (version: VersionResponse) => restoreVersion(file.id, version.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["versions", file.id] });
      // The file's own size/hash changed, so refresh the listings too.
      void queryClient.invalidateQueries({ queryKey: ["directory"] });
      void queryClient.invalidateQueries({ queryKey: ["search"] });
    },
    onError: (err) => reportError(err, "Could not restore that version."),
  });

  function handleRestore(version: VersionResponse) {
    const ok = window.confirm(
      `Make version ${version.version_number} the current version of "${file.name}"? ` +
        "The versions after it are kept.",
    );
    if (!ok) return;
    restoreMutation.mutate(version);
  }

  async function handleDownload(version: VersionResponse) {
    try {
      await downloadVersion(file.id, version.id, file.name);
    } catch (err) {
      reportError(err, "Could not download that version.");
    }
  }

  if (versionsQuery.isLoading) {
    return <p className="px-4 py-3 text-xs text-gray-500">Loading versions…</p>;
  }
  if (versionsQuery.isError || !versionsQuery.data) {
    return <p className="px-4 py-3 text-xs text-red-600">Could not load the version history.</p>;
  }

  return (
    <ul aria-label={`Versions of ${file.name}`} className="bg-gray-50 px-4 py-2">
      {versionsQuery.data.versions.map((version) => (
        <li
          key={version.id}
          className="flex items-center justify-between gap-3 border-b border-gray-200 py-2 text-xs last:border-b-0"
        >
          <span className="flex-1 truncate text-gray-700">
            <span className="font-medium text-gray-900">v{version.version_number}</span>
            {version.is_current && (
              <span className="ml-2 rounded bg-green-100 px-1.5 py-0.5 text-green-800">
                current
              </span>
            )}
            {version.restored_from_version !== null && (
              <span className="ml-2 text-gray-500">
                (restored from v{version.restored_from_version})
              </span>
            )}
            <span className="ml-2 text-gray-500">
              {formatBytes(version.size)} · {formatDateTime(version.created_at)}
            </span>
          </span>
          <span className="flex shrink-0 gap-2">
            <button
              onClick={() => void handleDownload(version)}
              className="text-gray-600 hover:underline"
            >
              Download
            </button>
            {!version.is_current && (
              <button
                onClick={() => handleRestore(version)}
                disabled={restoreMutation.isPending}
                className="text-gray-600 hover:underline disabled:opacity-50"
              >
                Restore
              </button>
            )}
          </span>
        </li>
      ))}
    </ul>
  );
}
