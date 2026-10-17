import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { ApiError } from "../api/client";
import { deleteFile, downloadFile, moveFile, renameFile } from "../api/files";
import { setFavorite } from "../api/library";
import { ConfirmDialog, FolderPicker, PromptDialog } from "../components/Dialogs";
import { ShareDialog } from "../components/ShareDialog";
import type { MenuItem } from "../components/RowMenu";
import type { FileResponse } from "../types/files";

type Dialog =
  | { kind: "rename"; file: FileResponse }
  | { kind: "move"; file: FileResponse }
  | { kind: "delete"; file: FileResponse }
  | { kind: "share"; file: FileResponse }
  | { kind: "error"; message: string };

const LISTS = ["directory", "search", "photos", "recent", "favorites", "usage", "activity", "trash", "versions"];

/**
 * Everything you can do to a file (favorite, rename, move, delete, download), with its
 * dialogs. Pages render `dialogs` once and use `menuFor(file)` / `toggleFavorite`.
 * `extra` adds page-specific menu items (e.g. "Versions" on the Files page).
 */
export function useFileActions(extra?: (file: FileResponse) => MenuItem[]) {
  const queryClient = useQueryClient();
  const [dialog, setDialog] = useState<Dialog | null>(null);

  function refresh() {
    for (const key of LISTS) void queryClient.invalidateQueries({ queryKey: [key] });
  }

  function fail(err: unknown, fallback: string) {
    setDialog({ kind: "error", message: err instanceof ApiError ? err.message : fallback });
  }

  const favoriteMutation = useMutation({
    mutationFn: (file: FileResponse) => setFavorite(file.id, !file.is_favorite),
    onSuccess: refresh,
    onError: (err) => fail(err, "Could not update favorites."),
  });
  const renameMutation = useMutation({
    mutationFn: ({ file, name }: { file: FileResponse; name: string }) => renameFile(file.id, name),
    onSuccess: () => {
      setDialog(null);
      refresh();
    },
    onError: (err) => fail(err, "Could not rename the file."),
  });
  const moveMutation = useMutation({
    mutationFn: ({ file, folderId }: { file: FileResponse; folderId: string | null }) => moveFile(file.id, folderId),
    onSuccess: () => {
      setDialog(null);
      refresh();
    },
    onError: (err) => fail(err, "Could not move the file."),
  });
  const deleteMutation = useMutation({
    mutationFn: (file: FileResponse) => deleteFile(file.id),
    onSuccess: () => {
      setDialog(null);
      refresh();
    },
    onError: (err) => fail(err, "Could not delete the file."),
  });

  async function download(file: FileResponse) {
    try {
      await downloadFile(file.id, file.name);
    } catch {
      setDialog({ kind: "error", message: `Could not download ${file.name}.` });
    }
  }

  function menuFor(file: FileResponse): MenuItem[] {
    return [
      { label: "Download", onSelect: () => void download(file) },
      { label: "Share link…", onSelect: () => setDialog({ kind: "share", file }) },
      ...(extra ? extra(file) : []),
      { label: "Rename", onSelect: () => setDialog({ kind: "rename", file }) },
      { label: "Move to…", onSelect: () => setDialog({ kind: "move", file }) },
      { label: "Move to trash", danger: true, onSelect: () => setDialog({ kind: "delete", file }) },
    ];
  }

  const dialogs: ReactNode = (() => {
    if (!dialog) return null;
    const close = () => setDialog(null);
    switch (dialog.kind) {
      case "rename":
        return (
          <PromptDialog
            title="Rename file"
            label="New name"
            initial={dialog.file.name}
            confirmLabel="Rename"
            onClose={close}
            onSubmit={(name) => {
              if (name === dialog.file.name) return close();
              renameMutation.mutate({ file: dialog.file, name });
            }}
          />
        );
      case "move":
        return (
          <FolderPicker
            title={`Move "${dialog.file.name}"`}
            onClose={close}
            onPick={(folderId) => moveMutation.mutate({ file: dialog.file, folderId })}
          />
        );
      case "delete":
        return (
          <ConfirmDialog
            title="Move to trash?"
            message={`"${dialog.file.name}" will go to the trash. You can restore it from there.`}
            confirmLabel="Move to trash"
            danger
            onClose={close}
            onConfirm={() => deleteMutation.mutate(dialog.file)}
          />
        );
      case "share":
        return (
          <ShareDialog
            target={{ kind: "file", id: dialog.file.id, name: dialog.file.name }}
            onClose={close}
          />
        );
      case "error":
        return (
          <ConfirmDialog
            title="Something went wrong"
            message={dialog.message}
            confirmLabel="OK"
            onClose={close}
            onConfirm={close}
          />
        );
    }
  })();

  return {
    menuFor,
    dialogs,
    download,
    toggleFavorite: (file: FileResponse) => favoriteMutation.mutate(file),
    deleteWithConfirm: (file: FileResponse) => setDialog({ kind: "delete", file }),
    showError: (message: string) => setDialog({ kind: "error", message }),
  };
}
