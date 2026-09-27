import { API_BASE_URL, apiDelete, apiGet, apiPatch, apiUpload, getAccessToken } from "./client";
import { CHUNKED_UPLOAD_THRESHOLD, uploadFileChunked } from "./uploads";
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
): Promise<FileResponse> {
  if (file.size > CHUNKED_UPLOAD_THRESHOLD) {
    return uploadFileChunked(file, folderId, onProgress);
  }

  const formData = new FormData();
  formData.append("file", file);
  if (folderId) formData.append("folder_id", folderId);

  if (!onProgress) {
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
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText) as FileResponse);
      } else {
        reject(new Error(`upload failed with status ${xhr.status}`));
      }
    };
    xhr.onerror = () => reject(new Error("upload failed"));
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

export async function downloadFile(id: string, filename: string): Promise<void> {
  const token = getAccessToken();
  const response = await fetch(`${API_BASE_URL}/api/files/${id}/download`, {
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
