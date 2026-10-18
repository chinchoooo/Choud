import { API_BASE_URL, apiDelete, apiGet, apiPatch, apiUpload, apiUploadWithProgress, getAccessToken } from "./client";
import {
  CHUNKED_UPLOAD_THRESHOLD,
  DEFAULT_CHUNK_SIZE,
  uploadFileChunked,
  type UploadOptions,
} from "./uploads";
import type { DirectoryListing, FileResponse, SearchResponse } from "../types/files";

export function listDirectory(folderId: string | null): Promise<DirectoryListing> {
  const query = folderId ? `?folder_id=${folderId}` : "";
  return apiGet<DirectoryListing>(`/api/files${query}`);
}

// Large files go through the resumable chunked-upload flow
// (api/uploads.ts) instead of one big multipart POST — see
// docs/architecture.md#10-chunked-uploads. A failed chunked upload throws
// `ResumableUploadError`, which carries the session id a caller can pass
// to `resumeUpload` to pick up where it left off.
export function uploadFile(
  file: File,
  folderId: string | null,
  onProgress?: (fraction: number) => void,
  options: UploadOptions = {},
): Promise<FileResponse> {
  if (file.size > CHUNKED_UPLOAD_THRESHOLD) {
    return uploadFileChunked(file, folderId, onProgress, DEFAULT_CHUNK_SIZE, options);
  }

  const formData = new FormData();
  formData.append("file", file);
  if (folderId) formData.append("folder_id", folderId);
  if (options.takenAt) formData.append("taken_at", options.takenAt);

  if (!onProgress && !options.signal && !options.onBytes) {
    return apiUpload<FileResponse>("/api/files/upload", formData);
  }

  // XHR (not fetch) so the browser reports upload progress while the bytes go out.
  return apiUploadWithProgress<FileResponse>(
    "/api/files/upload",
    formData,
    (loaded, total) => {
      onProgress?.(total > 0 ? loaded / total : 1);
      // `loaded` includes multipart framing; clamp to the real file size.
      options.onBytes?.(Math.min(file.size, loaded));
    },
    options.signal,
  );
}

export function renameFile(id: string, name: string): Promise<FileResponse> {
  return apiPatch<FileResponse>(`/api/files/${id}`, { name });
}

export function moveFile(id: string, folderId: string | null): Promise<FileResponse> {
  return apiPatch<FileResponse>(`/api/files/${id}`, { folder_id: folderId });
}

export function deleteFile(id: string): Promise<void> {
  return apiDelete<void>(`/api/files/${id}`);
}

export function search(query: string): Promise<SearchResponse> {
  return apiGet<SearchResponse>(`/api/search?q=${encodeURIComponent(query)}`);
}

// Fetches an authenticated endpoint and hands the bytes to the browser as a
// file download. A plain <a href> can't be used because the bearer token lives
// in localStorage, not in a cookie.
export async function downloadAuthenticated(path: string, filename: string): Promise<void> {
  const token = getAccessToken();
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  if (!response.ok) {
    throw new Error(`download failed with status ${response.status}`);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

/** Downloads the chosen files and folders as one .zip (built on the server). */
export async function downloadZip(fileIds: string[], folderIds: string[]): Promise<void> {
  const token = getAccessToken();
  const response = await fetch(`${API_BASE_URL}/api/archive/zip`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify({ file_ids: fileIds, folder_ids: folderIds }),
  });
  if (!response.ok) {
    let detail = `download failed with status ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // keep the generic message
    }
    throw new Error(detail);
  }
  const header = response.headers.get("Content-Disposition") ?? "";
  const match = /filename="?([^";]+)"?/.exec(header);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = match?.[1] ?? "choud.zip";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function downloadFile(id: string, filename: string): Promise<void> {
  return downloadAuthenticated(`/api/files/${id}/download`, filename);
}
