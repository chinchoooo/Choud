import { API_BASE_URL, apiDelete, apiGet, apiPatch, apiUpload, getAccessToken } from "./client";
import {
  CHUNKED_UPLOAD_THRESHOLD,
  DEFAULT_CHUNK_SIZE,
  UploadCancelled,
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

  if (!onProgress && !options.signal) {
    return apiUpload<FileResponse>("/api/files/upload", formData);
  }

  // XHR gives us upload progress events, which fetch() cannot — used only
  // when the caller wants a progress bar; the plain fetch path above is
  // used otherwise (and shares the client's auth/refresh handling).
  return new Promise<FileResponse>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE_URL}/api/files/upload`);
    const token = getAccessToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(event.loaded / event.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText) as FileResponse);
      } else {
        // Keep the server's own explanation (e.g. "storage quota exceeded") and the status.
        let detail = "";
        try {
          const body = JSON.parse(xhr.responseText) as { detail?: unknown };
          if (typeof body.detail === "string") detail = body.detail;
        } catch {
          // not JSON
        }
        const error = new Error(detail || `upload failed with status ${xhr.status}`);
        (error as Error & { status?: number }).status = xhr.status;
        reject(error);
      }
    };
    xhr.onerror = () => reject(new Error("upload failed: network error"));
    xhr.onabort = () => reject(new UploadCancelled());
    options.signal?.addEventListener("abort", () => xhr.abort(), { once: true });
    if (options.signal?.aborted) {
      reject(new UploadCancelled());
      return;
    }
    xhr.send(formData);
  });
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

export function downloadFile(id: string, filename: string): Promise<void> {
  return downloadAuthenticated(`/api/files/${id}/download`, filename);
}
