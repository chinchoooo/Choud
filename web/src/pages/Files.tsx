import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import {
  deleteFile,
  downloadFile,
  listDirectory,
  moveFile,
  renameFile,
  search as searchFiles,
  uploadFile,
} from "../api/files";
import { createFolder, deleteFolder, moveFolder, renameFolder } from "../api/folders";
import { ResumableUploadError, resumeUpload } from "../api/uploads";
import { useAuth } from "../auth/AuthContext";
import { formatBytes } from "../lib/format";
import type { FileResponse, FolderResponse } from "../types/files";

function reportError(err: unknown, fallback: string): void {
  window.alert(err instanceof ApiError ? err.message : fallback);
}

interface Crumb {
  id: string;
  name: string;
}

export function Files() {
  const { user, logout } = useAuth();
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [searchParams, setSearchParams] = useSearchParams();
  const folderId = searchParams.get("folder");
  const [trail, setTrail] = useState<Crumb[]>([]);
  const [searchInput, setSearchInput] = useState("");
  const [activeQuery, setActiveQuery] = useState("");
  // A large upload that failed partway through (network drop, etc.) —
  // kept around so "Resume upload" can pick up only the missing chunks
  // instead of starting over (docs/architecture.md#10-chunked-uploads).
  const [pausedUpload, setPausedUpload] = useState<{ uploadId: string; file: File } | null>(null);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);

  const directoryQuery = useQuery({
    queryKey: ["directory", folderId],
    queryFn: () => listDirectory(folderId),
  });

  const searchQuery = useQuery({
    queryKey: ["search", activeQuery],
    queryFn: () => searchFiles(activeQuery),
    enabled: activeQuery.length > 0,
  });

  const isSearching = activeQuery.length > 0;

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ["directory"] });
    void queryClient.invalidateQueries({ queryKey: ["search"] });
  }

  const createFolderMutation = useMutation({
    mutationFn: (name: string) => createFolder(name, folderId),
    onSuccess: invalidate,
    onError: (err) => reportError(err, "Could not create folder."),
  });

  const uploadMutation = useMutation({
    mutationFn: (file: File) =>
      uploadFile(file, folderId, (fraction) => setUploadProgress(fraction)),
    onSuccess: () => {
      setUploadProgress(null);
      setPausedUpload(null);
      invalidate();
    },
    onError: (err, file) => {
      setUploadProgress(null);
      if (err instanceof ResumableUploadError) {
        // Large-file chunked upload: the session is still alive
        // server-side with whatever chunks did arrive — offer to resume
        // instead of forcing a full restart.
        setPausedUpload({ uploadId: err.uploadId, file });
        reportError(err, "Upload interrupted — you can resume it below.");
        return;
      }
      reportError(err, "Could not upload file.");
    },
  });

  const resumeUploadMutation = useMutation({
    mutationFn: ({ uploadId, file }: { uploadId: string; file: File }) =>
      resumeUpload(uploadId, file, (fraction) => setUploadProgress(fraction)),
    onSuccess: () => {
      setUploadProgress(null);
      setPausedUpload(null);
      invalidate();
    },
    onError: (err) => {
      setUploadProgress(null);
      // The session id in `pausedUpload` is still valid — keep it so the
      // person can just try "Resume" again.
      reportError(err, "Still couldn't finish the upload — try Resume again.");
    },
  });

  const renameFolderMutation = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => renameFolder(id, name),
    onSuccess: invalidate,
    onError: (err) => reportError(err, "Could not rename folder."),
  });

  const moveFolderMutation = useMutation({
    mutationFn: ({ id, parentId }: { id: string; parentId: string | null }) =>
      moveFolder(id, parentId),
    onSuccess: invalidate,
    onError: (err) => reportError(err, "Could not move folder."),
  });

  const deleteFolderMutation = useMutation({
    mutationFn: (id: string) => deleteFolder(id),
    onSuccess: invalidate,
    onError: (err) => reportError(err, "Could not delete folder — is it empty?"),
  });

  const renameFileMutation = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => renameFile(id, name),
    onSuccess: invalidate,
    onError: (err) => reportError(err, "Could not rename file."),
  });

  const moveFileMutation = useMutation({
    mutationFn: ({ id, folderId: target }: { id: string; folderId: string | null }) =>
      moveFile(id, target),
    onSuccess: invalidate,
    onError: (err) => reportError(err, "Could not move file."),
  });

  const deleteFileMutation = useMutation({
    mutationFn: (id: string) => deleteFile(id),
    onSuccess: invalidate,
    onError: (err) => reportError(err, "Could not delete file."),
  });

  function openFolder(folder: FolderResponse) {
    setActiveQuery("");
    setSearchInput("");
    setTrail((prev) => {
      const idx = prev.findIndex((c) => c.id === folder.id);
      if (idx >= 0) return prev.slice(0, idx + 1);
      return [...prev, { id: folder.id, name: folder.name }];
    });
    setSearchParams({ folder: folder.id });
  }

  function goHome() {
    setTrail([]);
    setSearchParams({});
  }

  function goToCrumb(index: number) {
    setTrail((prev) => prev.slice(0, index + 1));
    setSearchParams({ folder: breadcrumbs[index].id });
  }

  const currentFolderName = directoryQuery.data?.folder?.name ?? null;
  const breadcrumbs: Crumb[] =
    trail.length > 0
      ? trail
      : folderId && currentFolderName
        ? [{ id: folderId, name: currentFolderName }]
        : [];

  function handleSearchSubmit(event: FormEvent) {
    event.preventDefault();
    setActiveQuery(searchInput.trim());
  }

  function clearSearch() {
    setSearchInput("");
    setActiveQuery("");
  }

  function handleCreateFolder() {
    const name = window.prompt("Folder name:");
    if (!name) return;
    createFolderMutation.mutate(name);
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    uploadMutation.mutate(file);
  }

  function handleRenameFolder(folder: FolderResponse) {
    const name = window.prompt("New folder name:", folder.name);
    if (!name || name === folder.name) return;
    renameFolderMutation.mutate({ id: folder.id, name });
  }

  function handleMoveFolder(folder: FolderResponse) {
    const target = window.prompt("Destination folder ID (leave blank for Home):", "");
    if (target === null) return;
    moveFolderMutation.mutate({ id: folder.id, parentId: target.trim() || null });
  }

  function handleDeleteFolder(folder: FolderResponse) {
    if (!window.confirm(`Delete folder "${folder.name}"? It must be empty.`)) return;
    deleteFolderMutation.mutate(folder.id);
  }

  function handleRenameFile(file: FileResponse) {
    const name = window.prompt("New file name:", file.name);
    if (!name || name === file.name) return;
    renameFileMutation.mutate({ id: file.id, name });
  }

  function handleMoveFile(file: FileResponse) {
    const target = window.prompt("Destination folder ID (leave blank for Home):", "");
    if (target === null) return;
    moveFileMutation.mutate({ id: file.id, folderId: target.trim() || null });
  }

  function handleDeleteFile(file: FileResponse) {
    if (!window.confirm(`Delete "${file.name}"?`)) return;
    deleteFileMutation.mutate(file.id);
  }

  async function handleDownload(file: FileResponse) {
    try {
      await downloadFile(file.id, file.name);
    } catch (err) {
      reportError(err, "Could not download file.");
    }
  }

  const subfolders = isSearching ? (searchQuery.data?.folders ?? []) : (directoryQuery.data?.subfolders ?? []);
  const files = isSearching ? (searchQuery.data?.files ?? []) : (directoryQuery.data?.files ?? []);
  const isLoading = isSearching ? searchQuery.isLoading : directoryQuery.isLoading;
  const isError = isSearching ? searchQuery.isError : directoryQuery.isError;

  return (
    <div className="mx-auto max-w-4xl p-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">My Cloud</h1>
          <p className="mt-1 text-sm text-gray-500">Signed in as {user?.email}</p>
        </div>
        <button
          onClick={() => void logout()}
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
        >
          Log out
        </button>
      </div>

      <form onSubmit={handleSearchSubmit} className="mt-6 flex gap-2">
        <input
          type="search"
          value={searchInput}
          onChange={(event) => setSearchInput(event.target.value)}
          placeholder="Search your files and folders…"
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
        />
        <button
          type="submit"
          className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50"
        >
          Search
        </button>
        {isSearching && (
          <button
            type="button"
            onClick={clearSearch}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50"
          >
            Clear
          </button>
        )}
      </form>

      {!isSearching && (
        <nav className="mt-6 flex flex-wrap items-center gap-1 text-sm text-gray-500">
          <button onClick={goHome} className="hover:text-gray-900 hover:underline">
            Home
          </button>
          {breadcrumbs.map((crumb, index) => (
            <span key={crumb.id} className="flex items-center gap-1">
              <span>/</span>
              <button onClick={() => goToCrumb(index)} className="hover:text-gray-900 hover:underline">
                {crumb.name}
              </button>
            </span>
          ))}
        </nav>
      )}

      {!isSearching && (
        <div className="mt-4 flex gap-2">
          <button
            onClick={handleCreateFolder}
            className="rounded-md bg-gray-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-gray-800"
          >
            New folder
          </button>
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploadMutation.isPending}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            {uploadMutation.isPending ? "Uploading…" : "Upload file"}
          </button>
          <input ref={fileInputRef} type="file" className="hidden" onChange={handleFileChange} />
          {uploadProgress !== null && (
            <span className="self-center text-xs text-gray-500">
              {Math.round(uploadProgress * 100)}%
            </span>
          )}
          {pausedUpload && (
            <button
              onClick={() => resumeUploadMutation.mutate(pausedUpload)}
              disabled={resumeUploadMutation.isPending}
              className="rounded-md border border-amber-300 bg-amber-50 px-3 py-1.5 text-sm text-amber-800 hover:bg-amber-100 disabled:opacity-50"
            >
              {resumeUploadMutation.isPending
                ? "Resuming…"
                : `Resume upload of "${pausedUpload.file.name}"`}
            </button>
          )}
        </div>
      )}

      <div className="mt-6 overflow-hidden rounded-lg border border-gray-200">
        {isLoading && <p className="p-4 text-sm text-gray-500">Loading…</p>}
        {isError && <p className="p-4 text-sm text-red-600">Could not load this listing.</p>}
        {!isLoading && !isError && subfolders.length === 0 && files.length === 0 && (
          <p className="p-4 text-sm text-gray-500">
            {isSearching ? "No matches." : "This folder is empty."}
          </p>
        )}

        {subfolders.map((folder) => (
          <div
            key={folder.id}
            className="flex items-center justify-between border-b border-gray-100 px-4 py-3 last:border-b-0"
          >
            <button
              onClick={() => openFolder(folder)}
              className="flex-1 truncate text-left text-sm font-medium text-gray-900 hover:underline"
            >
              📁 {folder.name}
            </button>
            <span className="mr-3 hidden font-mono text-xs text-gray-400 sm:inline">
              {folder.id.slice(0, 8)}
            </span>
            <div className="flex shrink-0 gap-2 text-xs">
              <button onClick={() => handleRenameFolder(folder)} className="text-gray-600 hover:underline">
                Rename
              </button>
              <button onClick={() => handleMoveFolder(folder)} className="text-gray-600 hover:underline">
                Move
              </button>
              <button onClick={() => handleDeleteFolder(folder)} className="text-red-600 hover:underline">
                Delete
              </button>
            </div>
          </div>
        ))}

        {files.map((file) => (
          <div
            key={file.id}
            className="flex items-center justify-between border-b border-gray-100 px-4 py-3 last:border-b-0"
          >
            <span className="flex-1 truncate text-sm text-gray-900">📄 {file.name}</span>
            <span className="mr-3 hidden text-xs text-gray-400 sm:inline">
              {formatBytes(file.size)}
            </span>
            <div className="flex shrink-0 gap-2 text-xs">
              <button onClick={() => void handleDownload(file)} className="text-gray-600 hover:underline">
                Download
              </button>
              <button onClick={() => handleRenameFile(file)} className="text-gray-600 hover:underline">
                Rename
              </button>
              <button onClick={() => handleMoveFile(file)} className="text-gray-600 hover:underline">
                Move
              </button>
              <button onClick={() => handleDeleteFile(file)} className="text-red-600 hover:underline">
                Delete
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
