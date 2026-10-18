// Resumable chunked uploads (Phase 5) — see docs/architecture.md#10-chunked-uploads.
//
// A plain fetch chain, per the Phase 5 plan in docs/roadmap.md: no upload library,
// just create a session, slice the File client-side with File.slice(),
// POST each chunk, then complete. `resumeUpload` re-reads the session's
// status first and only (re)sends chunks the server doesn't already
// have — that's the whole "resumable" story, both for a call that failed
// partway and for a deliberate retry later.

import { RequestAborted, apiDelete, apiGet, apiPost, apiUpload, apiUploadWithProgress } from "./client";
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

// Options shared by the upload helpers: `signal` cancels between requests, `takenAt`
// (ISO string) is stored as the photo's "taken" date so the timeline sorts correctly.
export interface UploadOptions {
  signal?: AbortSignal;
  takenAt?: string;
  /**
   * Bytes of the whole file sent so far, reported many times per chunk (not just when a
   * chunk finishes). Giving this switches chunks to XHR so progress is smooth.
   */
  onBytes?: (loaded: number) => void;
}

export { RequestAborted as UploadCancelled };
const UploadCancelled = RequestAborted;

function throwIfCancelled(signal?: AbortSignal): void {
  if (signal?.aborted) throw new UploadCancelled();
}

function createSession(
  fileName: string,
  fileSize: number,
  folderId: string | null,
  chunkSize: number,
  takenAt?: string,
): Promise<UploadSessionResponse> {
  return apiPost<UploadSessionResponse>("/api/uploads", {
    file_name: fileName,
    file_size: fileSize,
    chunk_size: chunkSize,
    folder_id: folderId,
    ...(takenAt ? { taken_at: takenAt } : {}),
  });
}

export function getUploadStatus(uploadId: string): Promise<UploadStatusResponse> {
  return apiGet<UploadStatusResponse>(`/api/uploads/${uploadId}`);
}

function uploadChunk(
  uploadId: string,
  index: number,
  blob: Blob,
  onChunkBytes?: (loaded: number) => void,
  signal?: AbortSignal,
): Promise<ChunkAckResponse> {
  const formData = new FormData();
  formData.append("chunk", blob);
  const path = `/api/uploads/${uploadId}/chunks/${index}`;
  if (onChunkBytes) {
    return apiUploadWithProgress<ChunkAckResponse>(path, formData, (loaded) => onChunkBytes(loaded), signal);
  }
  return apiUpload<ChunkAckResponse>(path, formData);
}

async function uploadChunkWithRetry(
  uploadId: string,
  index: number,
  blob: Blob,
  onChunkBytes?: (loaded: number) => void,
  signal?: AbortSignal,
): Promise<void> {
  let lastError: unknown;
  for (let attempt = 1; attempt <= MAX_CHUNK_ATTEMPTS; attempt++) {
    try {
      await uploadChunk(uploadId, index, blob, onChunkBytes, signal);
      return;
    } catch (err) {
      if (err instanceof RequestAborted) throw err;
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
  options: UploadOptions = {},
): Promise<FileResponse> {
  const status = await getUploadStatus(uploadId);
  let doneCount = status.total_chunks - status.missing_chunk_indices.length;
  onProgress?.(status.total_chunks === 0 ? 1 : doneCount / status.total_chunks);
  // Bytes already on the server (earlier attempts), so a resumed upload starts where it left off.
  let sentBytes = Math.min(file.size, doneCount * status.chunk_size);
  options.onBytes?.(sentBytes);

  try {
    for (const index of status.missing_chunk_indices) {
      throwIfCancelled(options.signal);
      const start = index * status.chunk_size;
      const blob = file.slice(start, start + status.chunk_size);
      const base = sentBytes;
      await uploadChunkWithRetry(
        uploadId,
        index,
        blob,
        options.onBytes ? (loaded) => options.onBytes?.(Math.min(file.size, base + loaded)) : undefined,
        options.signal,
      );
      sentBytes = Math.min(file.size, base + blob.size);
      options.onBytes?.(sentBytes);
      doneCount += 1;
      onProgress?.(doneCount / status.total_chunks);
    }
  } catch (err) {
    if (err instanceof UploadCancelled) {
      void abandonUpload(uploadId).catch(() => undefined); // free the half-uploaded chunks
      throw err;
    }
    throw new ResumableUploadError(uploadId, err);
  }

  return completeUpload(uploadId);
}

export async function uploadFileChunked(
  file: File,
  folderId: string | null,
  onProgress?: (fraction: number) => void,
  chunkSize: number = DEFAULT_CHUNK_SIZE,
  options: UploadOptions = {},
): Promise<FileResponse> {
  throwIfCancelled(options.signal);
  const session = await createSession(file.name, file.size, folderId, chunkSize, options.takenAt);
  return resumeUpload(session.id, file, onProgress, options);
}
