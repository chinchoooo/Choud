import { API_BASE_URL, apiDelete, apiGet, apiPost, apiPut } from "./client";
import type { ActivityItem, FileResponse, PhotoPage, Usage } from "../types/files";

export type PhotoKind = "all" | "image" | "video";

export function listPhotos(kind: PhotoKind, offset: number, limit = 120): Promise<PhotoPage> {
  return apiGet<PhotoPage>(`/api/library/photos?kind=${kind}&offset=${offset}&limit=${limit}`);
}

export function listRecent(limit = 50): Promise<FileResponse[]> {
  return apiGet<FileResponse[]>(`/api/library/recent?limit=${limit}`);
}

export function listFavorites(): Promise<FileResponse[]> {
  return apiGet<FileResponse[]>("/api/library/favorites");
}

export function setFavorite(fileId: string, favorite: boolean): Promise<void> {
  const path = `/api/library/favorites/${fileId}`;
  return favorite ? apiPut<void>(path) : apiDelete<void>(path);
}

export function getUsage(): Promise<Usage> {
  return apiGet<Usage>("/api/library/usage");
}

export interface MemoryGroup {
  year: number;
  years_ago: number;
  files: FileResponse[];
}

export function listMemories(): Promise<MemoryGroup[]> {
  return apiGet<MemoryGroup[]>("/api/library/memories");
}

export function listActivity(limit = 100): Promise<ActivityItem[]> {
  return apiGet<ActivityItem[]>(`/api/library/activity?limit=${limit}`);
}

export interface MediaTokenResponse {
  token: string;
  expires_in: number;
}

export function fetchMediaToken(): Promise<MediaTokenResponse> {
  return apiPost<MediaTokenResponse>("/api/media/token");
}

export function mediaContentUrl(token: string, fileId: string): string {
  return `${API_BASE_URL}/api/media/${token}/${fileId}/content`;
}

export function mediaThumbUrl(token: string, fileId: string, size: 128 | 256 | 512 | 1024): string {
  return `${API_BASE_URL}/api/media/${token}/${fileId}/thumbnail?size=${size}`;
}
