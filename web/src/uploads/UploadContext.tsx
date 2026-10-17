import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { uploadFile } from "../api/files";
import { ResumableUploadError, UploadCancelled, resumeUpload } from "../api/uploads";
import {
  MAX_ACTIVE_UPLOADS,
  MAX_AUTO_RETRIES,
  isTransientFailure,
  retryDelayMs,
  smoothSpeed,
  summarize,
  type QueueSummary,
  type UploadStatus,
} from "./queueMath";

export interface UploadItem {
  id: string;
  name: string;
  size: number;
  folderId: string | null;
  /** Where it is going, for display ("My files / Trips"). */
  destination: string;
  status: UploadStatus;
  loaded: number;
  /** Smoothed bytes per second while uploading. */
  speed: number;
  attempts: number;
  error?: string;
  /** When the next automatic retry fires (ms since epoch), while status is "retrying". */
  retryAt?: number;
  startedAt?: number;
  finishedAt?: number;
}

interface UploadContextValue {
  items: UploadItem[];
  summary: QueueSummary;
  enqueue: (files: File[], folderId: string | null, destination?: string) => void;
  cancel: (id: string) => void;
  retry: (id: string) => void;
  cancelAll: () => void;
  clearFinished: () => void;
}

const UploadContext = createContext<UploadContextValue | undefined>(undefined);

let nextId = 1;

export function UploadProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [items, setItems] = useState<UploadItem[]>([]);

  // Things that must not trigger renders live in refs: the File objects, abort
  // controllers, resumable chunk sessions and the speed-sampling clocks.
  const files = useRef(new Map<string, File>());
  const controllers = useRef(new Map<string, AbortController>());
  const sessions = useRef(new Map<string, string>());
  const samples = useRef(new Map<string, { at: number; loaded: number }>());
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const itemsRef = useRef<UploadItem[]>([]);
  itemsRef.current = items;

  const patch = useCallback((id: string, changes: Partial<UploadItem>) => {
    setItems((current) => current.map((item) => (item.id === id ? { ...item, ...changes } : item)));
  }, []);

  const refreshLists = useCallback(() => {
    for (const key of ["directory", "search", "photos", "recent", "favorites", "usage", "activity", "shares"]) {
      void queryClient.invalidateQueries({ queryKey: [key] });
    }
  }, [queryClient]);

  const runItem = useCallback(
    async (id: string) => {
      const file = files.current.get(id);
      if (!file) return;
      const item = itemsRef.current.find((candidate) => candidate.id === id);
      if (!item) return;

      const controller = new AbortController();
      controllers.current.set(id, controller);
      samples.current.set(id, { at: performance.now(), loaded: 0 });
      patch(id, {
        status: "uploading",
        startedAt: item.startedAt ?? Date.now(),
        error: undefined,
        retryAt: undefined,
        speed: 0,
      });

      const onBytes = (bytes: number) => {
        const loaded = Math.min(file.size, bytes);
        const sample = samples.current.get(id);
        const now = performance.now();
        let speedUpdate: number | undefined;
        if (sample && now - sample.at >= 400) {
          const instantaneous = Math.max(0, ((loaded - sample.loaded) / (now - sample.at)) * 1000);
          const previous = itemsRef.current.find((candidate) => candidate.id === id)?.speed ?? 0;
          speedUpdate = smoothSpeed(previous, instantaneous);
          samples.current.set(id, { at: now, loaded });
        }
        patch(id, speedUpdate === undefined ? { loaded } : { loaded, speed: speedUpdate });
      };

      const takenAt = file.lastModified ? new Date(file.lastModified).toISOString() : undefined;
      try {
        const sessionId = sessions.current.get(id);
        if (sessionId) {
          await resumeUpload(sessionId, file, undefined, { signal: controller.signal, takenAt, onBytes });
        } else {
          await uploadFile(file, item.folderId, undefined, { signal: controller.signal, takenAt, onBytes });
        }
        sessions.current.delete(id);
        files.current.delete(id);
        patch(id, { status: "done", loaded: file.size, speed: 0, finishedAt: Date.now() });
        refreshLists();
      } catch (error) {
        if (error instanceof UploadCancelled) {
          files.current.delete(id);
          sessions.current.delete(id);
          patch(id, { status: "cancelled", speed: 0, finishedAt: Date.now() });
          return;
        }
        if (error instanceof ResumableUploadError) sessions.current.set(id, error.uploadId);
        const attempts = (itemsRef.current.find((candidate) => candidate.id === id)?.attempts ?? 0) + 1;
        const message = error instanceof Error ? error.message : "upload failed";
        if (isTransientFailure(error) && attempts <= MAX_AUTO_RETRIES) {
          const delay = retryDelayMs(attempts);
          patch(id, { status: "retrying", attempts, error: message, speed: 0, retryAt: Date.now() + delay });
          timers.current.set(
            id,
            setTimeout(() => {
              timers.current.delete(id);
              patch(id, { status: "queued", retryAt: undefined });
            }, delay),
          );
        } else {
          patch(id, { status: "error", attempts, error: message, speed: 0, finishedAt: Date.now() });
        }
      } finally {
        controllers.current.delete(id);
      }
    },
    [patch, refreshLists],
  );

  // The scheduler: whenever the list changes, start queued items while slots are free.
  useEffect(() => {
    const active = items.filter((item) => item.status === "uploading").length;
    let slots = MAX_ACTIVE_UPLOADS - active;
    for (const item of items) {
      if (slots <= 0) break;
      if (item.status === "queued" && !controllers.current.has(item.id)) {
        slots -= 1;
        void runItem(item.id);
      }
    }
  }, [items, runItem]);

  // Leaving the page mid-upload would silently lose the queue; the browser asks first.
  const busy = useMemo(() => summarize(items).busy, [items]);
  useEffect(() => {
    if (!busy) return;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [busy]);

  // A 1-second tick keeps "retrying in 3s" and elapsed-time displays live.
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!busy) return;
    const id = setInterval(() => setTick((value) => value + 1), 1000);
    return () => clearInterval(id);
  }, [busy]);

  const enqueue = useCallback((picked: File[], folderId: string | null, destination = "My files") => {
    if (picked.length === 0) return;
    const created: UploadItem[] = picked.map((file) => {
      const id = `u${nextId++}`;
      files.current.set(id, file);
      return {
        id,
        name: file.name,
        size: file.size,
        folderId,
        destination,
        status: "queued",
        loaded: 0,
        speed: 0,
        attempts: 0,
      };
    });
    setItems((current) => [...current, ...created]);
  }, []);

  const cancel = useCallback((id: string) => {
    const timer = timers.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
    const controller = controllers.current.get(id);
    if (controller) {
      controller.abort(); // runItem marks it cancelled
      return;
    }
    files.current.delete(id);
    sessions.current.delete(id);
    setItems((current) =>
      current.map((item) =>
        item.id === id && (item.status === "queued" || item.status === "retrying")
          ? { ...item, status: "cancelled", speed: 0, finishedAt: Date.now() }
          : item,
      ),
    );
  }, []);

  const retry = useCallback((id: string) => {
    if (!files.current.has(id)) return; // the File is gone (cancelled earlier)
    setItems((current) =>
      current.map((item) =>
        item.id === id && item.status === "error"
          ? { ...item, status: "queued", attempts: 0, error: undefined }
          : item,
      ),
    );
  }, []);

  const cancelAll = useCallback(() => {
    for (const item of itemsRef.current) {
      if (item.status === "queued" || item.status === "uploading" || item.status === "retrying") {
        cancel(item.id);
      }
    }
  }, [cancel]);

  const clearFinished = useCallback(() => {
    setItems((current) =>
      current.filter((item) => item.status === "queued" || item.status === "uploading" || item.status === "retrying"),
    );
  }, []);

  const value = useMemo<UploadContextValue>(
    () => ({ items, summary: summarize(items), enqueue, cancel, retry, cancelAll, clearFinished }),
    [items, enqueue, cancel, retry, cancelAll, clearFinished],
  );
  return <UploadContext.Provider value={value}>{children}</UploadContext.Provider>;
}

export function useUploads(): UploadContextValue {
  const context = useContext(UploadContext);
  if (!context) throw new Error("useUploads must be used inside <UploadProvider>");
  return context;
}
