import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { HardDrive } from "lucide-react";
import { useState } from "react";

import { ApiError } from "../api/client";
import { fixPhotoDates, getSpace, pruneVersions, type FixDatesReport, type PruneReport } from "../api/insights";
import { ConfirmDialog, plainButton } from "../components/Dialogs";
import { formatBytes } from "../lib/format";

function Bar({ value, max, label }: { value: number; max: number; label: string }) {
  const pct = max > 0 ? Math.max(1, Math.round((value / max) * 100)) : 0;
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct}
      className="h-2 w-full overflow-hidden border border-gray-300 bg-gray-100"
    >
      <div className="h-full bg-gray-900" style={{ width: `${pct}%` }} />
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="border border-gray-200 bg-white p-3 rounded-md">
      <div className="text-xs text-gray-500">{label}</div>
      <div className="mt-1 text-lg font-semibold text-gray-900">{value}</div>
      {hint && <div className="mt-1 text-xs text-gray-500">{hint}</div>}
    </div>
  );
}

/** Where the space went: what deduplication saved, what old versions cost, the biggest files. */
export function Space() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["space"], queryFn: getSpace });
  const [keep, setKeep] = useState(5);
  const [preview, setPreview] = useState<PruneReport | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [dates, setDates] = useState<FixDatesReport | null>(null);

  const refresh = () => {
    setPreview(null);
    void queryClient.invalidateQueries({ queryKey: ["space"] });
    void queryClient.invalidateQueries({ queryKey: ["usage"] });
  };
  const previewMutation = useMutation({
    mutationFn: () => pruneVersions(keep, true),
    onSuccess: (report) => {
      setDone(null);
      setPreview(report);
    },
  });
  const prune = useMutation({
    mutationFn: () => pruneVersions(keep, false),
    onSuccess: (report) => {
      setConfirming(false);
      setDone(`Removed ${report.versions_removed} old version(s) and freed ${formatBytes(report.bytes_freed)}.`);
      refresh();
    },
  });

  const previewDates = useMutation({ mutationFn: () => fixPhotoDates(true), onSuccess: setDates });
  const applyDates = useMutation({
    mutationFn: () => fixPhotoDates(false),
    onSuccess: (report) => {
      setDates(null);
      setDone(`Fixed the dates of ${report.fixed} photo(s).`);
      void queryClient.invalidateQueries({ queryKey: ["photos"] });
    },
  });

  const data = query.data;
  if (query.isLoading) return <p className="p-6 text-sm text-gray-500">Loading…</p>;
  if (!data) return <p className="p-6 text-sm text-red-600">Could not load your storage report.</p>;

  const types = Object.entries(data.by_type);
  const error = [previewMutation.error, prune.error].find(Boolean);

  return (
    <div className="mx-auto max-w-4xl p-4 sm:p-6">
      <h1 className="flex items-center gap-2 text-lg font-semibold text-gray-900">
        <HardDrive size={18} aria-hidden /> Storage
      </h1>
      <p className="mt-1 text-sm text-gray-600">
        Identical files are stored once however many names they have, so the real size is smaller than the sum of
        your files.
      </p>

      <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Your files now" value={formatBytes(data.current_bytes)} />
        <Stat label="Saved by deduplication" value={formatBytes(data.dedup_saved_bytes)} hint="the same bytes kept once" />
        <Stat label="Old versions" value={formatBytes(data.history_bytes)} hint="only held by earlier versions" />
        <Stat label="In the trash" value={formatBytes(data.trash_bytes)} />
      </div>

      <section className="mt-6" aria-label="By type">
        <h2 className="text-sm font-medium text-gray-900">By type</h2>
        <ul className="mt-2 space-y-2">
          {types.length === 0 && <li className="text-sm text-gray-500">No files yet.</li>}
          {types.map(([name, bytes]) => (
            <li key={name}>
              <div className="flex justify-between text-sm text-gray-700">
                <span>{name}</span>
                <span>{formatBytes(bytes)}</span>
              </div>
              <Bar value={bytes} max={data.current_bytes} label={`${name} share of your files`} />
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-6" aria-label="Biggest files">
        <h2 className="text-sm font-medium text-gray-900">Biggest files</h2>
        <ul className="mt-2 divide-y divide-gray-200 border border-gray-200 bg-white rounded-md">
          {data.biggest.length === 0 && <li className="p-3 text-sm text-gray-500">Nothing yet.</li>}
          {data.biggest.map((file) => (
            <li key={file.id} className="flex justify-between gap-3 px-3 py-2 text-sm">
              <span className="truncate text-gray-900">{file.name}</span>
              <span className="shrink-0 text-gray-600">{formatBytes(file.size)}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-6" aria-label="Duplicates">
        <h2 className="text-sm font-medium text-gray-900">Duplicate files ({data.duplicate_files} extra copies)</h2>
        <p className="mt-1 text-xs text-gray-500">
          The same content under different names. They share one stored copy, so this is clutter rather than disk space.
        </p>
        <ul className="mt-2 divide-y divide-gray-200 border border-gray-200 bg-white rounded-md">
          {data.duplicates.length === 0 && <li className="p-3 text-sm text-gray-500">No duplicates found.</li>}
          {data.duplicates.map((group, index) => (
            <li key={index} className="px-3 py-2 text-sm">
              <span className="text-gray-600">
                {group.copies} copies, {formatBytes(group.size)} each:{" "}
              </span>
              <span className="text-gray-900">{group.files.map((f) => f.name).join(", ")}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-6 border border-gray-300 p-4 rounded-md" aria-label="Photo dates">
        <h2 className="text-sm font-medium text-gray-900">Photo dates</h2>
        <p className="mt-1 text-sm text-gray-600">
          Photos uploaded without a date show up on the day they were uploaded. This reads the real date from the file name
          (IMG_20250206_160717.jpg and similar) or the photo's own data, and puts the photos in the right place on the timeline.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" className={plainButton} disabled={previewDates.isPending} onClick={() => previewDates.mutate()}>
            Preview
          </button>
          {dates && dates.fixed > 0 && (
            <button type="button" className={plainButton} disabled={applyDates.isPending} onClick={() => applyDates.mutate()}>
              Fix {dates.fixed} photo(s)
            </button>
          )}
        </div>
        {dates && (
          <p role="status" className="mt-3 text-sm text-gray-800">
            {dates.fixed === 0
              ? `Nothing to fix (${dates.checked} photo(s) without a date, ${dates.no_date_found} with no date to be found).`
              : `${dates.fixed} of ${dates.checked} undated photo(s) can be fixed (${dates.from_name} from names, ${dates.from_exif} from photo data). ${dates.examples[0] ?? ""}`}
          </p>
        )}
      </section>

      <section className="mt-6 border border-gray-300 p-4 rounded-md" aria-label="Clean up old versions">
        <h2 className="text-sm font-medium text-gray-900">Clean up old versions</h2>
        <p className="mt-1 text-sm text-gray-600">
          Keep only the newest versions of each file. The current version always stays. Removed versions cannot be
          restored or rewound to.
        </p>
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <label className="text-sm text-gray-700">
            Keep the newest
            <select
              value={keep}
              onChange={(event) => {
                setKeep(Number(event.target.value));
                setPreview(null);
              }}
              className="mt-1 block border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 rounded-md"
            >
              {[1, 2, 3, 5, 10, 20].map((n) => (
                <option key={n} value={n}>
                  {n} version{n === 1 ? "" : "s"}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className={plainButton} disabled={previewMutation.isPending} onClick={() => previewMutation.mutate()}>
            Preview
          </button>
          {preview && preview.versions_removed > 0 && (
            <button type="button" className={plainButton} onClick={() => setConfirming(true)}>
              Remove them
            </button>
          )}
        </div>
        {preview && (
          <p role="status" className="mt-3 text-sm text-gray-800">
            {preview.versions_removed === 0
              ? "Nothing to remove."
              : `This would remove ${preview.versions_removed} version(s) across ${preview.files_affected} file(s) and free about ${formatBytes(preview.bytes_freed)}.`}
          </p>
        )}
      </section>

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
          title="Remove old versions?"
          message={`${preview.versions_removed} old version(s) will be removed for good, freeing about ${formatBytes(preview.bytes_freed)}. You will not be able to restore them.`}
          confirmLabel="Remove"
          danger
          onConfirm={() => prune.mutate()}
          onClose={() => setConfirming(false)}
        />
      )}
    </div>
  );
}
