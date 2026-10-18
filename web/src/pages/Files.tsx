import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type ChangeEvent, type DragEvent } from "react";
import { useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { deleteFile, downloadZip, listDirectory, moveFile, search as searchFiles } from "../api/files";
import { createFolder, deleteFolder, getFolder, moveFolder, renameFolder } from "../api/folders";
import { BulkBar } from "../components/BulkBar";
import { ConfirmDialog, FolderPicker, PromptDialog, plainButton, primaryButton } from "../components/Dialogs";
import { FileCollection, ViewToggle, loadViewMode, saveViewMode, type ViewMode } from "../components/FileCollection";
import { FileViewer } from "../components/FileViewer";
import { ShareDialog } from "../components/ShareDialog";
import { VersionHistory } from "../components/VersionHistory";
import { useFileActions } from "../hooks/useFileActions";
import { ensureFolderPath, fromDrop, fromPickedFolder, groupByDir, type TreeFile } from "../lib/folderUpload";
import { useUploads } from "../uploads/UploadContext";
import type { FolderResponse } from "../types/files";

type FolderDialog =
  | { kind: "new" }
  | { kind: "rename"; folder: FolderResponse }
  | { kind: "move"; folder: FolderResponse }
  | { kind: "delete"; folder: FolderResponse }
  | { kind: "share"; folder: FolderResponse }
  | { kind: "error"; message: string };

export function Files() {
  const queryClient = useQueryClient();
  const { enqueue } = useUploads();
  const fileInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);

  const [params, setParams] = useSearchParams();
  const folderId = params.get("folder");
  const searchText = (params.get("q") ?? "").trim();
  const isSearching = searchText.length > 0;

  const [mode, setMode] = useState<ViewMode>(loadViewMode);
  const [viewerIndex, setViewerIndex] = useState<number | null>(null);
  const [versionsFor, setVersionsFor] = useState<string | null>(null);
  const [folderDialog, setFolderDialog] = useState<FolderDialog | null>(null);
  const [dragging, setDragging] = useState(false);
  // Bulk selection: files and folders chosen with the checkboxes.
  const [selectMode, setSelectMode] = useState(false);
  const [selFiles, setSelFiles] = useState<Set<string>>(new Set());
  const [selFolders, setSelFolders] = useState<Set<string>>(new Set());
  const [bulkDialog, setBulkDialog] = useState<null | "move" | "trash">(null);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkMessage, setBulkMessage] = useState<string | null>(null);
  const dragDepth = useRef(0);

  const actions = useFileActions((file) => [
    {
      label: versionsFor === file.id ? "Hide versions" : "Versions",
      onSelect: () => setVersionsFor((open) => (open === file.id ? null : file.id)),
    },
  ]);

  const directory = useQuery({
    queryKey: ["directory", folderId],
    queryFn: () => listDirectory(folderId),
    refetchInterval: 20_000, // pauses while the tab is hidden
  });
  const searchQuery = useQuery({
    queryKey: ["search", searchText],
    queryFn: () => searchFiles(searchText),
    enabled: isSearching,
  });

  // Breadcrumbs: walk up from the current folder to the root.
  const crumbs = useQuery({
    queryKey: ["crumbs", folderId],
    enabled: !!folderId,
    queryFn: async () => {
      const chain: FolderResponse[] = [];
      let id: string | null = folderId;
      while (id && chain.length < 32) {
        const folder = await getFolder(id);
        chain.unshift(folder);
        id = folder.parent_id;
      }
      return chain;
    },
  });

  const folders = useMemo(
    () => (isSearching ? (searchQuery.data?.folders ?? []) : (directory.data?.subfolders ?? [])),
    [isSearching, searchQuery.data, directory.data],
  );
  const nameFiles = useMemo(
    () => (isSearching ? (searchQuery.data?.files ?? []) : (directory.data?.files ?? [])),
    [isSearching, searchQuery.data, directory.data],
  );
  const contentHits = useMemo(
    () => (isSearching ? (searchQuery.data?.content ?? []) : []),
    [isSearching, searchQuery.data],
  );
  // The viewer steps through name matches first, then the files found by their contents.
  const files = useMemo(
    () => [...nameFiles, ...contentHits.map((hit) => hit.file)],
    [nameFiles, contentHits],
  );
  const loading = isSearching ? searchQuery.isLoading : directory.isLoading;
  const failed = isSearching ? searchQuery.isError : directory.isError;
  const destination = crumbs.data?.length ? `My files / ${crumbs.data.map((c) => c.name).join(" / ")}` : "My files";

  // A folder that was deleted or moved away while open should not strand the user.
  useEffect(() => {
    if (directory.error instanceof ApiError && directory.error.status === 404 && folderId) {
      setParams({});
    }
  }, [directory.error, folderId, setParams]);

  function refresh() {
    for (const key of ["directory", "search", "crumbs", "picker", "trash"]) {
      void queryClient.invalidateQueries({ queryKey: [key] });
    }
  }
  function folderError(err: unknown, fallback: string) {
    setFolderDialog({ kind: "error", message: err instanceof ApiError ? err.message : fallback });
  }

  const createMutation = useMutation({
    mutationFn: (name: string) => createFolder(name, folderId),
    onSuccess: () => {
      setFolderDialog(null);
      refresh();
    },
    onError: (err) => folderError(err, "Could not create the folder."),
  });
  const renameMutation = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => renameFolder(id, name),
    onSuccess: () => {
      setFolderDialog(null);
      refresh();
    },
    onError: (err) => folderError(err, "Could not rename the folder."),
  });
  const moveMutation = useMutation({
    mutationFn: ({ id, parentId }: { id: string; parentId: string | null }) => moveFolder(id, parentId),
    onSuccess: () => {
      setFolderDialog(null);
      refresh();
    },
    onError: (err) => folderError(err, "Could not move the folder."),
  });
  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteFolder(id),
    onSuccess: () => {
      setFolderDialog(null);
      refresh();
    },
    onError: (err) => folderError(err, "Could not delete the folder. Is it empty?"),
  });

  // Moving to another folder or searching starts a fresh selection.
  useEffect(() => {
    setSelFiles(new Set());
    setSelFolders(new Set());
    setBulkMessage(null);
  }, [folderId, searchText]);

  function toggle(set: Set<string>, id: string): Set<string> {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  }
  function endSelecting() {
    setSelectMode(false);
    setSelFiles(new Set());
    setSelFolders(new Set());
    setBulkMessage(null);
  }
  const selectedCount = selFiles.size + selFolders.size;
  const selectableTotal = nameFiles.length + folders.length;
  function selectAllOrNone() {
    if (selectedCount === selectableTotal) {
      setSelFiles(new Set());
      setSelFolders(new Set());
    } else {
      setSelFiles(new Set(nameFiles.map((file) => file.id)));
      setSelFolders(new Set(folders.map((folder) => folder.id)));
    }
  }

  /** Runs one request per item, then says how many worked, so one failure never hides the rest. */
  async function runBulk(label: string, jobs: (() => Promise<unknown>)[]) {
    setBulkBusy(true);
    setBulkMessage(null);
    const results = await Promise.allSettled(jobs.map((job) => job()));
    const failed = results.filter((result) => result.status === "rejected").length;
    setBulkBusy(false);
    setSelFiles(new Set());
    setSelFolders(new Set());
    setBulkMessage(
      failed === 0
        ? `${label}: ${results.length} done.`
        : `${label}: ${results.length - failed} done, ${failed} could not be changed (a non-empty folder, or a name already taken).`,
    );
    refresh();
    void queryClient.invalidateQueries({ queryKey: ["usage"] });
  }
  async function bulkDownload() {
    setBulkBusy(true);
    setBulkMessage(null);
    try {
      await downloadZip([...selFiles], [...selFolders]);
      setBulkMessage("Download started.");
    } catch (err) {
      setBulkMessage(err instanceof Error ? err.message : "Could not build the zip.");
    } finally {
      setBulkBusy(false);
    }
  }
  function bulkMove(destination: string | null) {
    setBulkDialog(null);
    void runBulk("Move", [
      ...[...selFiles].map((id) => () => moveFile(id, destination)),
      ...[...selFolders].map((id) => () => moveFolder(id, destination)),
    ]);
  }
  function bulkTrash() {
    setBulkDialog(null);
    void runBulk("Delete", [
      ...[...selFiles].map((id) => () => deleteFile(id)),
      ...[...selFolders].map((id) => () => deleteFolder(id)),
    ]);
  }

  function openFolder(folder: FolderResponse) {
    setVersionsFor(null);
    setParams({ folder: folder.id });
  }

  function changeMode(next: ViewMode) {
    setMode(next);
    saveViewMode(next);
  }

  /** Uploads files that sit in sub-folders: the folders are created first, then each group queued. */
  async function uploadTree(tree: TreeFile[]) {
    const here = (crumbs.data ?? []).map((crumb) => crumb.name).join("/");
    try {
      for (const [dir, group] of groupByDir(tree)) {
        if (dir === "") {
          enqueue(group, folderId, destination);
          continue;
        }
        const id = await ensureFolderPath(here ? `${here}/${dir}` : dir);
        enqueue(group, id, `${destination} / ${dir.replaceAll("/", " / ")}`);
      }
      refresh();
    } catch (err) {
      setFolderDialog({ kind: "error", message: err instanceof ApiError ? err.message : "Could not create the folders." });
    }
  }

  function pickFolder(event: ChangeEvent<HTMLInputElement>) {
    const picked = Array.from(event.target.files ?? []);
    event.target.value = "";
    void uploadTree(fromPickedFolder(picked));
  }

  function pickFiles(event: ChangeEvent<HTMLInputElement>) {
    const picked = Array.from(event.target.files ?? []);
    event.target.value = "";
    enqueue(picked, folderId, destination);
  }

  // Drag & drop anywhere on the page. Dropped folders are uploaded with their structure.
  function onDragEnter(event: DragEvent) {
    if (!event.dataTransfer.types.includes("Files")) return;
    dragDepth.current += 1;
    setDragging(true);
  }
  function onDragLeave() {
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) setDragging(false);
  }
  function onDrop(event: DragEvent) {
    event.preventDefault();
    dragDepth.current = 0;
    setDragging(false);
    if (event.dataTransfer.items?.length) {
      void fromDrop(event.dataTransfer.items).then((tree) => {
        if (tree.length > 0) void uploadTree(tree);
      });
      return;
    }
    enqueue(Array.from(event.dataTransfer.files), folderId, destination);
  }

  return (
    <div
      className="relative mx-auto max-w-5xl p-4 sm:p-6"
      onDragEnter={onDragEnter}
      onDragOver={(event) => event.preventDefault()}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      {dragging && (
        <div className="pointer-events-none absolute inset-2 z-30 flex items-center justify-center border-2 border-dashed border-gray-900 bg-white/80 text-lg text-gray-900">
          Drop to upload to {destination}
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        {isSearching ? (
          <h1 className="text-lg font-semibold text-gray-900">Results for “{searchText}”</h1>
        ) : (
          <nav aria-label="Folder path" className="flex flex-wrap items-center gap-1 text-sm text-gray-500">
            <button onClick={() => setParams({})} className="text-gray-900 hover:underline">
              My files
            </button>
            {(crumbs.data ?? []).map((crumb, index, all) => (
              <span key={crumb.id} className="flex items-center gap-1">
                <span>/</span>
                {index === all.length - 1 ? (
                  <span className="font-medium text-gray-900">{crumb.name}</span>
                ) : (
                  <button onClick={() => setParams({ folder: crumb.id })} className="hover:underline">
                    {crumb.name}
                  </button>
                )}
              </span>
            ))}
          </nav>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <ViewToggle mode={mode} onChange={changeMode} />
          {!isSearching && (
            <>
              <button onClick={() => setSelectMode((on) => !on)} aria-pressed={selectMode} className={plainButton}>
                Select
              </button>
              <button onClick={() => setFolderDialog({ kind: "new" })} className={plainButton}>
                New folder
              </button>
              <button onClick={() => folderInput.current?.click()} className={plainButton}>
                Upload folder
              </button>
              <button onClick={() => fileInput.current?.click()} className={primaryButton}>
                Upload files
              </button>
              <input
                ref={folderInput}
                type="file"
                multiple
                className="hidden"
                onChange={pickFolder}
                {...({ webkitdirectory: "", directory: "" } as Record<string, string>)}
              />
              <input ref={fileInput} type="file" multiple className="hidden" onChange={pickFiles} />
            </>
          )}
          {isSearching && (
            <button onClick={() => setParams({})} className={plainButton}>
              Clear search
            </button>
          )}
        </div>
      </div>

      {selectMode && !isSearching && (
        <BulkBar
          count={selectedCount}
          total={selectableTotal}
          busy={bulkBusy}
          message={bulkMessage}
          onSelectAll={selectAllOrNone}
          onDownload={() => void bulkDownload()}
          onMove={() => setBulkDialog("move")}
          onTrash={() => setBulkDialog("trash")}
          onClear={endSelecting}
        />
      )}

      <div className="mt-4">
        {loading && <p className="p-4 text-sm text-gray-500">Loading…</p>}
        {failed && <p className="p-4 text-sm text-red-600">Could not load this listing.</p>}
        {!loading && !failed && (
          <FileCollection
            folders={folders}
            files={nameFiles}
            mode={mode}
            showPath={isSearching}
            empty={
              isSearching
                ? contentHits.length > 0
                  ? "No file names match."
                  : "No matches."
                : "This folder is empty. Drop files here or use “Upload files”."
            }
            onOpenFolder={openFolder}
            onOpenFile={(index) => setViewerIndex(index)}
            onToggleFavorite={actions.toggleFavorite}
            onDownload={(file) => void actions.download(file)}
            fileMenu={actions.menuFor}
            selection={
              selectMode && !isSearching
                ? {
                    files: selFiles,
                    folders: selFolders,
                    toggleFile: (id) => setSelFiles((set) => toggle(set, id)),
                    toggleFolder: (id) => setSelFolders((set) => toggle(set, id)),
                  }
                : undefined
            }
            folderMenu={(folder) => [
              { label: "Open", onSelect: () => openFolder(folder) },
              { label: "Share link…", onSelect: () => setFolderDialog({ kind: "share", folder }) },
              { label: "Rename", onSelect: () => setFolderDialog({ kind: "rename", folder }) },
              { label: "Move to…", onSelect: () => setFolderDialog({ kind: "move", folder }) },
              { label: "Delete (must be empty)", danger: true, onSelect: () => setFolderDialog({ kind: "delete", folder }) },
            ]}
            expandedFor={versionsFor}
            renderExpanded={(file) => <VersionHistory file={file} />}
          />
        )}
        {!loading && !failed && contentHits.length > 0 && (
          <section aria-label="Matches inside files" className="mt-6">
            <h2 className="text-sm font-medium text-gray-900">Found inside files</h2>
            <ul className="mt-2 divide-y divide-gray-200 border border-gray-200 bg-white rounded-lg">
              {contentHits.map((hit, index) => (
                <li key={hit.file.id}>
                  <button
                    onClick={() => setViewerIndex(nameFiles.length + index)}
                    className="block w-full px-4 py-3 text-left hover:bg-gray-50"
                  >
                    <span className="block text-sm font-medium text-gray-900">{hit.file.name}</span>
                    <span className="block text-xs text-gray-500">{hit.file.folder_path || "My files"}</span>
                    <span className="mt-1 block text-sm text-gray-700">{hit.snippet}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>

      {bulkDialog === "move" && (
        <FolderPicker
          title={`Move ${selectedCount} item${selectedCount === 1 ? "" : "s"}`}
          onPick={bulkMove}
          onClose={() => setBulkDialog(null)}
        />
      )}
      {bulkDialog === "trash" && (
        <ConfirmDialog
          title="Delete the selected items?"
          message={`${selFiles.size} file(s) go to the trash and can be restored. ${selFolders.size} folder(s) are removed only if they are empty.`}
          confirmLabel="Delete"
          danger
          onConfirm={bulkTrash}
          onClose={() => setBulkDialog(null)}
        />
      )}

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

      {folderDialog?.kind === "new" && (
        <PromptDialog
          title="New folder"
          label="Folder name"
          confirmLabel="Create"
          onClose={() => setFolderDialog(null)}
          onSubmit={(name) => createMutation.mutate(name)}
        />
      )}
      {folderDialog?.kind === "rename" && (
        <PromptDialog
          title="Rename folder"
          label="New name"
          initial={folderDialog.folder.name}
          confirmLabel="Rename"
          onClose={() => setFolderDialog(null)}
          onSubmit={(name) => renameMutation.mutate({ id: folderDialog.folder.id, name })}
        />
      )}
      {folderDialog?.kind === "move" && (
        <FolderPicker
          title={`Move folder "${folderDialog.folder.name}"`}
          excludeFolderId={folderDialog.folder.id}
          onClose={() => setFolderDialog(null)}
          onPick={(parentId) => moveMutation.mutate({ id: folderDialog.folder.id, parentId })}
        />
      )}
      {folderDialog?.kind === "delete" && (
        <ConfirmDialog
          title="Delete folder?"
          message={`Delete the folder "${folderDialog.folder.name}"? It must be empty.`}
          confirmLabel="Delete"
          danger
          onClose={() => setFolderDialog(null)}
          onConfirm={() => deleteMutation.mutate(folderDialog.folder.id)}
        />
      )}
      {folderDialog?.kind === "share" && (
        <ShareDialog
          target={{ kind: "folder", id: folderDialog.folder.id, name: folderDialog.folder.name }}
          onClose={() => setFolderDialog(null)}
        />
      )}
      {folderDialog?.kind === "error" && (
        <ConfirmDialog
          title="Something went wrong"
          message={folderDialog.message}
          confirmLabel="OK"
          onClose={() => setFolderDialog(null)}
          onConfirm={() => setFolderDialog(null)}
        />
      )}
      {actions.dialogs}
    </div>
  );
}
