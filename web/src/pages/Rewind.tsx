import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { History } from "lucide-react";
import { useState } from "react";

import { ApiError } from "../api/client";
import { browsePast, restorePastFile, restorePastTree, type RewindReport } from "../api/rewind";
import { ConfirmDialog, plainButton, primaryButton } from "../components/Dialogs";
import { formatBytes, formatDateTime } from "../lib/format";

const PRESETS: { label: string; hours: number }[] = [
  { label: "1 hour ago", hours: 1 },
  { label: "Yesterday", hours: 24 },
  { label: "A week ago", hours: 24 * 7 },
  { label: "A month ago", hours: 24 * 30 },
];

/** `<input type="datetime-local">` wants local time without a zone. */
function toLocalInput(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function hoursAgo(hours: number): Date {
  return new Date(Date.now() - hours * 3_600_000);
}

function summary(report: RewindReport): string {
  const parts = [
    `${report.restored_content} file${report.restored_content === 1 ? "" : "s"} put back to older content`,
    `${report.undeleted} taken out of the trash`,
  ];
  if (report.newer_untouched > 0) parts.push(`${report.newer_untouched} newer file${report.newer_untouched === 1 ? "" : "s"} left alone`);
  return parts.join(", ");
}

/** Browse your files as they were at an earlier time, and put them back. An undo for the whole drive. */
export function Rewind() {
  const queryClient = useQueryClient();
  const [when, setWhen] = useState(() => toLocalInput(hoursAgo(24)));
  const [folderId, setFolderId] = useState<string | null>(null);
  const [trail, setTrail] = useState<{ id: string; name: string }[]>([]);
  const [preview, setPreview] = useState<RewindReport | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [done, setDone] = useState<string | null>(null);

  const at = new Date(when);
  const valid = !Number.isNaN(at.getTime()) && at.getTime() < Date.now();
  const iso = valid ? at.toISOString() : "";

  const listing = useQuery({
    queryKey: ["rewind", iso, folderId],
    queryFn: () => browsePast(iso, folderId),
    enabled: valid,
  });

  const refresh = () => {
    setPreview(null);
    void queryClient.invalidateQueries({ queryKey: ["rewind"] });
    void queryClient.invalidateQueries({ queryKey: ["directory"] });
    void queryClient.invalidateQueries({ queryKey: ["trash"] });
  };

  const previewMutation = useMutation({
    mutationFn: () => restorePastTree(folderId, iso, true),
    onSuccess: (report) => {
      setDone(null);
      setPreview(report);
    },
  });
  const restoreTree = useMutation({
    mutationFn: () => restorePastTree(folderId, iso, false),
    onSuccess: (report) => {
      setConfirming(false);
      setDone(`Done: ${summary(report)}.`);
      refresh();
    },
  });
  const restoreFile = useMutation({
    mutationFn: (id: string) => restorePastFile(id, iso),
    onSuccess: (report) => {
      setDone(`Done: ${summary(report)}.`);
      refresh();
    },
  });

  function open(folder: { id: string; name: string }) {
    setTrail((t) => [...t, folder]);
    setFolderId(folder.id);
    setPreview(null);
  }
  function goTo(index: number) {
    const next = trail.slice(0, index);
    setTrail(next);
    setFolderId(next.length ? next[next.length - 1].id : null);
    setPreview(null);
  }
  function changeTime(value: string) {
    setWhen(value);
    setPreview(null);
    setDone(null);
  }

  const error = [previewMutation.error, restoreTree.error, restoreFile.error, listing.error].find(Boolean);
  const scope = trail.length ? `"${trail[trail.length - 1].name}" and everything inside it` : "all your files";
  const data = listing.data;

  return (
    <div className="mx-auto max-w-4xl p-4 sm:p-6">
      <h1 className="flex items-center gap-2 text-lg font-semibold text-gray-900">
        <History size={18} aria-hidden /> Rewind
      </h1>
      <p className="mt-1 text-sm text-gray-600">
        See your files as they were at an earlier time and put them back. Nothing is deleted by rewinding: the version
        you rewind away from stays in the file's history, and files made after that time are left alone.
      </p>

      <div className="mt-4 flex flex-wrap items-end gap-3">
        <label className="text-sm text-gray-700">
          Go back to
          <input
            type="datetime-local"
            value={when}
            max={toLocalInput(new Date())}
            onChange={(event) => changeTime(event.target.value)}
            className="mt-1 block border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 rounded-md"
          />
        </label>
        <div className="flex flex-wrap gap-2">
          {PRESETS.map((preset) => (
            <button key={preset.label} type="button" className={plainButton} onClick={() => changeTime(toLocalInput(hoursAgo(preset.hours)))}>
              {preset.label}
            </button>
          ))}
        </div>
      </div>
      {!valid && <p className="mt-2 text-sm text-red-600">Choose a time in the past.</p>}

      {valid && (
        <>
          <nav aria-label="Folder path" className="mt-5 flex flex-wrap items-center gap-1 text-sm text-gray-500">
            <button onClick={() => goTo(0)} className="text-gray-900 hover:underline">
              My files
            </button>
            {trail.map((folder, index) => (
              <span key={folder.id} className="flex items-center gap-1">
                <span>/</span>
                {index === trail.length - 1 ? (
                  <span className="font-medium text-gray-900">{folder.name}</span>
                ) : (
                  <button onClick={() => goTo(index + 1)} className="hover:underline">
                    {folder.name}
                  </button>
                )}
              </span>
            ))}
          </nav>

          <ul className="mt-3 divide-y divide-gray-200 border border-gray-200 bg-white rounded-lg">
            {listing.isLoading && <li className="p-3 text-sm text-gray-500">Loading…</li>}
            {data && data.folders.length === 0 && data.files.length === 0 && (
              <li className="p-3 text-sm text-gray-500">Nothing was here at that time.</li>
            )}
            {data?.folders.map((folder) => (
              <li key={folder.id}>
                <button onClick={() => open(folder)} className="w-full px-4 py-2 text-left text-sm font-medium text-gray-900 hover:bg-gray-50">
                  [+] {folder.name}
                </button>
              </li>
            ))}
            {data?.files.map((file) => (
              <li key={file.id} className="flex flex-wrap items-center gap-3 px-4 py-2 text-sm">
                <span className="min-w-0 flex-1 truncate text-gray-900" title={file.name}>
                  {file.name}
                </span>
                <span className="text-xs text-gray-500">{formatBytes(file.size)}</span>
                <span className="text-xs text-gray-500">version {file.version_number}</span>
                {file.trashed && <span className="border border-gray-300 px-1.5 text-xs text-gray-700">in trash now</span>}
                {file.changed && <span className="border border-gray-300 px-1.5 text-xs text-gray-700">changed since</span>}
                <button
                  type="button"
                  className={plainButton}
                  disabled={(!file.changed && !file.trashed) || restoreFile.isPending}
                  onClick={() => restoreFile.mutate(file.id)}
                >
                  Put back
                </button>
              </li>
            ))}
          </ul>
          {data && <p className="mt-1 text-xs text-gray-500">As of {formatDateTime(data.at)}</p>}

          <div className="mt-5 border border-gray-300 p-4 rounded-md">
            <h2 className="text-sm font-medium text-gray-900">Put back {scope}</h2>
            <p className="mt-1 text-sm text-gray-600">Preview first: nothing changes until you confirm.</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <button type="button" className={plainButton} disabled={previewMutation.isPending} onClick={() => previewMutation.mutate()}>
                Preview
              </button>
              {preview && preview.restored_content + preview.undeleted > 0 && (
                <button type="button" className={primaryButton} onClick={() => setConfirming(true)}>
                  Put everything back
                </button>
              )}
            </div>
            {preview && (
              <p role="status" className="mt-3 text-sm text-gray-800">
                {preview.restored_content + preview.undeleted === 0
                  ? "Everything here already matches that time."
                  : `This would change ${preview.restored_content + preview.undeleted} file(s): ${summary(preview)}.`}
              </p>
            )}
          </div>
        </>
      )}

      {done && (
        <p role="status" className="mt-3 text-sm text-gray-800">
          {done}
        </p>
      )}
      {error && (
        <p role="alert" className="mt-3 text-sm text-red-600">
          {error instanceof ApiError ? error.message : "Something went wrong."}
        </p>
      )}

      {confirming && preview && (
        <ConfirmDialog
          title="Put everything back?"
          message={`${summary(preview)}. Each restored file gets a new version, so what you have now is kept in its history.`}
          confirmLabel="Put back"
          onConfirm={() => restoreTree.mutate()}
          onClose={() => setConfirming(false)}
        />
      )}
    </div>
  );
}
