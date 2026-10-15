import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type ChangeEvent, type DragEvent } from "react";
import { useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { listDirectory, search as searchFiles } from "../api/files";
import { createFolder, deleteFolder, getFolder, moveFolder, renameFolder } from "../api/folders";
import { ConfirmDialog, FolderPicker, PromptDialog, plainButton, primaryButton } from "../components/Dialogs";
import { FileCollection, ViewToggle, loadViewMode, saveViewMode, type ViewMode } from "../components/FileCollection";
import { FileViewer } from "../components/FileViewer";
import { VersionHistory } from "../components/VersionHistory";
import { useFileActions } from "../hooks/useFileActions";
import { useUploads } from "../uploads/UploadContext";
import type { FolderResponse } from "../types/files";

type FolderDialog =
  | { kind: "new" }
  | { kind: "rename"; folder: FolderResponse }
  | { kind: "move"; folder: FolderResponse }
  | { kind: "delete"; folder: FolderResponse }
  | { kind: "error"; message: string };

export function Files() {
  const queryClient = useQueryClient();
  const { enqueue } = useUploads();
  const fileInput = useRef<HTMLInputElement>(null);

  const [params, setParams] = useSearchParams();
  const folderId = params.get("folder");
  const searchText = (params.get("q") ?? "").trim();
  const isSearching = searchText.length > 0;

  const [mode, setMode] = useState<ViewMode>(loadViewMode);
  const [viewerIndex, setViewerIndex] = useState<number | null>(null);
  const [versionsFor, setVersionsFor] = useState<string | null>(null);
  const [folderDialog, setFolderDialog] = useState<FolderDialog | null>(null);
  const [dragging, setDragging] = useState(false);
  const dragDepth = useRef(0);

  const actions = useFileActions((file) => [
    {
      label: versionsFor === file.id ? "Hide versions" : "Versions",
      onSelect: () => setVersionsFor((open) => (open === file.id ? null : file.id)),
    },
  ]);

  const directory = useQuery({ queryKey: ["directory", folderId], queryFn: () => listDirectory(folderId) });
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
  const files = useMemo(
    () => (isSearching ? (searchQuery.data?.files ?? []) : (directory.data?.files ?? [])),
    [isSearching, searchQuery.data, directory.data],
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

  function openFolder(folder: FolderResponse) {
    setVersionsFor(null);
    setParams({ folder: folder.id });
  }

  function changeMode(next: ViewMode) {
    setMode(next);
    saveViewMode(next);
  }

  function pickFiles(event: ChangeEvent<HTMLInputElement>) {
    const picked = Array.from(event.target.files ?? []);
    event.target.value = "";
    enqueue(picked, folderId, destination);
  }

  // Drag & drop anywhere on the page. Folders dropped are skipped (they have no size/type).
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
    const dropped = Array.from(event.dataTransfer.files).filter((file) => file.type !== "" || file.size > 0);
    enqueue(dropped, folderId, destination);
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
              <button onClick={() => setFolderDialog({ kind: "new" })} className={plainButton}>
                New folder
              </button>
              <button onClick={() => fileInput.current?.click()} className={primaryButton}>
                Upload files
              </button>
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

      <div className="mt-4">
        {loading && <p className="p-4 text-sm text-gray-500">Loading…</p>}
        {failed && <p className="p-4 text-sm text-red-600">Could not load this listing.</p>}
        {!loading && !failed && (
          <FileCollection
            folders={folders}
            files={files}
            mode={mode}
            showPath={isSearching}
            empty={
              isSearching
                ? "No matches."
                : "This folder is empty. Drop files here or use “Upload files”."
            }
            onOpenFolder={openFolder}
            onOpenFile={(index) => setViewerIndex(index)}
            onToggleFavorite={actions.toggleFavorite}
            onDownload={(file) => void actions.download(file)}
            fileMenu={actions.menuFor}
            folderMenu={(folder) => [
              { label: "Open", onSelect: () => openFolder(folder) },
              { label: "Rename", onSelect: () => setFolderDialog({ kind: "rename", folder }) },
              { label: "Move to…", onSelect: () => setFolderDialog({ kind: "move", folder }) },
              { label: "Delete (must be empty)", danger: true, onSelect: () => setFolderDialog({ kind: "delete", folder }) },
            ]}
            expandedFor={versionsFor}
            renderExpanded={(file) => <VersionHistory file={file} />}
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
