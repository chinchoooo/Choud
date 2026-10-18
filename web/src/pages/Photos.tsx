import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { listMemories, listPhotos, type PhotoKind } from "../api/library";
import { FileViewer } from "../components/FileViewer";
import { Thumb } from "../components/Thumb";
import { useFileActions } from "../hooks/useFileActions";
import type { FileResponse } from "../types/files";

const PAGE = 120;

function takenAt(file: FileResponse): Date {
  return new Date(file.taken_at ?? file.created_at);
}

/** "October 2026" style heading used to group the timeline. */
export function monthLabel(date: Date): string {
  if (Number.isNaN(date.getTime())) return "Unknown date";
  return date.toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

const FILTERS: { id: PhotoKind; label: string }[] = [
  { id: "all", label: "All" },
  { id: "image", label: "Photos" },
  { id: "video", label: "Videos" },
];

export function Photos() {
  const [kind, setKind] = useState<PhotoKind>("all");
  const [viewerIndex, setViewerIndex] = useState<number | null>(null);
  const actions = useFileActions();
  const memories = useQuery({ queryKey: ["memories"], queryFn: listMemories, staleTime: 5 * 60_000 });
  // The viewer can show either the timeline or one "on this day" group.
  const [memoryViewer, setMemoryViewer] = useState<{ files: FileResponse[]; index: number } | null>(null);

  const query = useInfiniteQuery({
    queryKey: ["photos", kind],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => listPhotos(kind, pageParam, PAGE),
    getNextPageParam: (last) => (last.offset + last.items.length < last.total ? last.offset + last.items.length : undefined),
  });

  const items = useMemo(() => query.data?.pages.flatMap((page) => page.items) ?? [], [query.data]);
  const total = query.data?.pages[0]?.total ?? 0;

  const groups = useMemo(() => {
    const out: { label: string; entries: { file: FileResponse; index: number }[] }[] = [];
    items.forEach((file, index) => {
      const label = monthLabel(takenAt(file));
      const last = out[out.length - 1];
      if (last && last.label === label) last.entries.push({ file, index });
      else out.push({ label, entries: [{ file, index }] });
    });
    return out;
  }, [items]);

  return (
    <div className="mx-auto max-w-6xl p-4 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">Photos</h1>
          <p className="text-xs text-gray-500">
            {query.isSuccess ? `${total} item${total === 1 ? "" : "s"}, newest first` : "Loading…"}
          </p>
        </div>
        <div role="group" aria-label="Filter" className="inline-flex">
          {FILTERS.map((filter, i) => (
            <button
              key={filter.id}
              onClick={() => setKind(filter.id)}
              aria-pressed={kind === filter.id}
              className={`border border-gray-300 px-3 py-1.5 text-sm ${i > 0 ? "-ml-px" : ""} ${
                kind === filter.id ? "bg-gray-900 text-white" : "bg-white text-gray-700 hover:bg-gray-100"
              }`}
            >
              {filter.label}
            </button>
          ))}
        </div>
      </div>

      {(memories.data ?? []).length > 0 && (
        <section aria-label="On this day" className="mt-5 border border-gray-300 p-3 rounded-md">
          <h2 className="text-sm font-semibold text-gray-900">On this day</h2>
          {(memories.data ?? []).map((group) => (
            <div key={group.year} className="mt-2">
              <p className="text-xs text-gray-500">
                {group.years_ago === 1 ? "1 year ago" : `${group.years_ago} years ago`} ({group.year})
              </p>
              <div className="mt-1 flex gap-1 overflow-x-auto">
                {group.files.map((file, index) => (
                  <button
                    key={file.id}
                    onClick={() => setMemoryViewer({ files: group.files, index })}
                    aria-label={`Open memory ${file.name}`}
                    className="relative block h-24 w-24 shrink-0 overflow-hidden bg-gray-100"
                  >
                    <Thumb file={file} size={256} className="h-full w-full text-xs" />
                  </button>
                ))}
              </div>
            </div>
          ))}
        </section>
      )}

      {query.isError && <p className="mt-4 text-sm text-red-600">Could not load your photos.</p>}
      {query.isSuccess && items.length === 0 && (
        <p className="mt-6 border border-gray-200 bg-white p-6 text-sm text-gray-500 rounded-lg">
          No photos or videos yet. Back up your phone or upload some.
        </p>
      )}

      {groups.map((group) => (
        <section key={group.label} className="mt-6">
          <h2 className="mb-2 text-sm font-semibold text-gray-700">{group.label}</h2>
          <div className="grid grid-cols-3 gap-1 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8">
            {group.entries.map(({ file, index }) => (
              <button
                key={file.id}
                onClick={() => setViewerIndex(index)}
                aria-label={`Open ${file.name}`}
                className="relative block aspect-square overflow-hidden bg-gray-100"
              >
                <Thumb file={file} size={256} className="h-full w-full text-xs" />
                {file.is_favorite && (
                  <span className="absolute left-1 top-1 bg-white/80 px-1 text-xs leading-4 text-amber-500">★</span>
                )}
              </button>
            ))}
          </div>
        </section>
      ))}

      {query.hasNextPage && (
        <div className="mt-6 text-center">
          <button
            onClick={() => void query.fetchNextPage()}
            disabled={query.isFetchingNextPage}
            className="border border-gray-300 bg-white px-4 py-2 text-sm text-gray-700 hover:bg-gray-100 disabled:opacity-50 rounded-md"
          >
            {query.isFetchingNextPage ? "Loading…" : `Load more (${items.length} of ${total})`}
          </button>
        </div>
      )}

      {viewerIndex !== null && (
        <FileViewer
          files={items}
          index={Math.min(viewerIndex, Math.max(items.length - 1, 0))}
          onIndexChange={(next) => {
            setViewerIndex(next);
            // Reaching the last loaded photo pulls in the next page.
            if (next >= items.length - 3 && query.hasNextPage && !query.isFetchingNextPage) void query.fetchNextPage();
          }}
          onClose={() => setViewerIndex(null)}
          onToggleFavorite={actions.toggleFavorite}
          onDelete={(file) => {
            setViewerIndex(null);
            actions.deleteWithConfirm(file);
          }}
        />
      )}
      {memoryViewer && (
        <FileViewer
          files={memoryViewer.files}
          index={memoryViewer.index}
          onIndexChange={(next) => setMemoryViewer({ ...memoryViewer, index: next })}
          onClose={() => setMemoryViewer(null)}
          onToggleFavorite={actions.toggleFavorite}
        />
      )}
      {actions.dialogs}
    </div>
  );
}
