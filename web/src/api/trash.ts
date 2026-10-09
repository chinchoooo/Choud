import { apiDelete, apiGet, apiPost } from "./client";
import type { FileResponse } from "../types/files";
import type { TrashListResponse } from "../types/trash";

export function listTrash(): Promise<TrashListResponse> {
  return apiGet<TrashListResponse>("/api/trash");
}

// The server puts the file back in its original folder (or the root if that
// folder is gone) and renames it "name (restored).ext" on a name clash, so the
// returned metadata can differ from what was shown in the trash.
export function restoreFromTrash(id: string): Promise<FileResponse> {
  return apiPost<FileResponse>(`/api/trash/${id}/restore`);
}

// Permanent. There is no undo.
export function purgeFromTrash(id: string): Promise<void> {
  return apiDelete<void>(`/api/trash/${id}`);
}
