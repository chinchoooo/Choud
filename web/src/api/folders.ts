import { apiDelete, apiGet, apiPatch, apiPost } from "./client";
import type { FolderResponse } from "../types/files";

export function createFolder(name: string, parentId: string | null): Promise<FolderResponse> {
  return apiPost<FolderResponse>("/api/folders", { name, parent_id: parentId });
}

export function renameFolder(id: string, name: string): Promise<FolderResponse> {
  return apiPatch<FolderResponse>(`/api/folders/${id}`, { name });
}

export function moveFolder(id: string, parentId: string | null): Promise<FolderResponse> {
  return apiPatch<FolderResponse>(`/api/folders/${id}`, { parent_id: parentId });
}

export function deleteFolder(id: string): Promise<void> {
  return apiDelete<void>(`/api/folders/${id}`);
}

export function getFolder(id: string): Promise<FolderResponse> {
  return apiGet<FolderResponse>(`/api/folders/${id}`);
}
