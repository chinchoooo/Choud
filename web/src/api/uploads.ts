// Resumable chunked uploads (Phase 5) — see docs/architecture.md#10-chunked-uploads.
//
// A plain fetch chain, per CLAUDE.md's Phase 5 plan: no upload library,
// just create a session, slice the File client-side with File.slice(),
// POST each chunk, then complete. `resumeUpload` re-reads the session's
// status first and only (re)sends chunks the server doesn't already
// have — that's the whole "resumable" story, both for a call that failed
// partway and for a deliberate retry later.

import { apiDelete, apiGet, apiPost, apiUpload } from "./client";
import type { ChunkAckResponse, UploadSessionResponse, UploadStatusResponse } from "../types/uploads";
import type { FileResponse } from "../types/files";

// Large enough that a typical file isn't split into hundreds of
// requests, small enough that a single chunk failure doesn't waste much
// of an unreliable connection. Not tuned against anything beyond that —
// revisit if real usage shows a better number.
export const DEFAULT_CHUNK_SIZE = 5 * 1024 * 1024; // 5 MiB

// Files smaller than this just use the plain POST /api/files/upload
// path (uploadFile in api/files.ts) — chunking a small file adds
// round trips for no benefit.
export const CHUNKED_UPLOAD_THRESHOLD = 20 * 1024 * 1024; // 20 MiB

const MAX_CHUNK_ATTEMPTS = 3;

function createSession(
  fileName: string,
  fileSize: number,
  folderId: string | null,
  chunkSize: number,
): Promise<UploadSessionResponse> {
  return apiPost<UploadSessionResponse>("/api/uploads", {
    file_name: fileName,
    file_size: fileSize,
    chunk_size: chunkSize,
    folder_id: folderId,
  });
}

export function getUploadStatus(uploadId: string): Promise<UploadStatusResponse> {
  return apiGet<UploadStatusResponse>(`/api/uploads/${uploadId}`);
}

function uploadChunk(uploadId: string, index: number, blob: Blob): Promise<ChunkAckResponse> {
  const formData = new FormData();
  formData.append("chunk", blob);
  return apiUpload<ChunkAckResponse>(`/api/uploads/${uploadId}/chunks/${index}`, formData);
}

async function uploadChunkWithRetry(uploadId: string, index: number, blob: Blob): Promise<void> {
  let lastError: unknown;
  for (let attempt = 1; attempt <= MAX_CHUNK_ATTEMPTS; attempt++) {
    try {
      await uploadChunk(uploadId, index, blob);
      return;
    } catch (err) {
      lastError = err;
      if (attempt < MAX_CHUNK_ATTEMPTS) {
        await new Promise((resolve) => setTimeout(resolve, 500 * attempt));
      }
    }
  }
  throw lastError;
}

function completeUpload(uploadId: string): Promise<FileResponse> {
  return apiPost<FileResponse>(`/api/uploads/${uploadId}/complete`);
}

export function abandonUpload(uploadId: string): Promise<void> {
  return apiDelete<void>(`/api/uploads/${uploadId}`);
}

// An upload that failed partway carries the session id it can be resumed
// with — the caller (see pages/Files.tsx) can offer a "Resume" action
// that calls `resumeUpload(err.uploadId, file, ...)` instead of starting
// over from chunk 0.
export class ResumableUploadError extends Error {
  uploadId: string;

  constructor(uploadId: string, cause: unknown) {
    super(cause instanceof Error ? cause.message : "upload failed");
    this.uploadId = uploadId;
  }
}

// Sends every chunk the session's status says is still missing, then
// completes it. Safe to call more than once for the same `uploadId` —
// each call only (re)sends what's actually absent server-side.
export async function resumeUpload(
  uploadId: string,
  file: File,
  onProgress?: (fraction: number) => void,
): Promise<FileResponse> {
  const status = await getUploadStatus(uploadId);
  let doneCount = status.total_chunks - status.missing_chunk_indices.length;
  onProgress?.(status.total_chunks === 0 ? 1 : doneCount / status.total_chunks);

  try {
    for (const index of status.missing_chunk_indices) {
      const start = index * status.chunk_size;
      const blob = file.slice(start, start + status.chunk_size);
      await uploadChunkWithRetry(uploadId, index, blob);
      doneCount += 1;
      onProgress?.(doneCount / status.total_chunks);
    }
  } catch (err) {
    throw new ResumableUploadError(uploadId, err);
  }

  return completeUpload(uploadId);
}

export async function uploadFileChunked(
  file: File,
  folderId: string | null,
  onProgress?: (fraction: number) => void,
  chunkSize: number = DEFAULT_CHUNK_SIZE,
): Promise<FileResponse> {
  const session = await createSession(file.name, file.size, folderId, chunkSize);
  return resumeUpload(session.id, file, onProgress);
}
