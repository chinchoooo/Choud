// Pure helpers behind the upload queue, kept free of React so they are easy to test.

export const MAX_ACTIVE_UPLOADS = 3;
export const MAX_AUTO_RETRIES = 3;

/** Exponential smoothing so the speed readout doesn't jitter on every progress event. */
export function smoothSpeed(previous: number, instantaneous: number, alpha = 0.3): number {
  if (previous <= 0) return instantaneous;
  return alpha * instantaneous + (1 - alpha) * previous;
}

/** Seconds left at the current speed, or null while the speed is unknown. */
export function etaSeconds(remainingBytes: number, bytesPerSecond: number): number | null {
  if (remainingBytes <= 0) return 0;
  if (!Number.isFinite(bytesPerSecond) || bytesPerSecond <= 0) return null;
  return remainingBytes / bytesPerSecond;
}

/** Wait before automatic retry number `attempt` (1-based): 2s, 5s, 15s. */
export function retryDelayMs(attempt: number): number {
  return [2_000, 5_000, 15_000][Math.min(Math.max(attempt, 1), 3) - 1];
}

/**
 * Worth retrying automatically? Network failures and 5xx/429 yes; a 4xx (quota exceeded,
 * name rejected, not logged in) will fail the same way again, so show it right away.
 */
export function isTransientFailure(error: unknown): boolean {
  const status = (error as { status?: number } | null)?.status;
  if (typeof status === "number") return status >= 500 || status === 429;
  return true; // no HTTP status at all: the connection dropped
}

export type UploadStatus = "queued" | "uploading" | "retrying" | "done" | "error" | "cancelled";

export interface QueueItemLike {
  status: UploadStatus;
  size: number;
  loaded: number;
  speed: number;
}

export interface QueueSummary {
  total: number;
  done: number;
  failed: number;
  uploading: number;
  waiting: number;
  bytesTotal: number;
  bytesLoaded: number;
  speed: number;
  etaSeconds: number | null;
  /** True while anything is still queued, uploading or about to retry. */
  busy: boolean;
}

export function summarize(items: QueueItemLike[]): QueueSummary {
  let done = 0;
  let failed = 0;
  let uploading = 0;
  let waiting = 0;
  let bytesTotal = 0;
  let bytesLoaded = 0;
  let speed = 0;
  for (const item of items) {
    if (item.status === "cancelled") continue;
    bytesTotal += item.size;
    if (item.status === "done") {
      done += 1;
      bytesLoaded += item.size;
    } else if (item.status === "error") {
      failed += 1;
      bytesLoaded += item.loaded;
    } else {
      bytesLoaded += item.loaded;
      if (item.status === "uploading") {
        uploading += 1;
        speed += item.speed;
      } else {
        waiting += 1;
      }
    }
  }
  const busy = uploading + waiting > 0;
  return {
    total: items.filter((item) => item.status !== "cancelled").length,
    done,
    failed,
    uploading,
    waiting,
    bytesTotal,
    bytesLoaded,
    speed,
    etaSeconds: busy ? etaSeconds(bytesTotal - bytesLoaded, speed) : 0,
    busy,
  };
}
