import { apiGet, apiPost } from "./client";

export interface SpaceReport {
  quota_bytes: number;
  logical_bytes: number;
  stored_bytes: number;
  dedup_saved_bytes: number;
  current_bytes: number;
  trash_bytes: number;
  history_bytes: number;
  by_type: Record<string, number>;
  biggest: { id: string; name: string; size: number }[];
  duplicates: { size: number; copies: number; files: { id: string; name: string }[] }[];
  duplicate_files: number;
}

export interface PruneReport {
  dry_run: boolean;
  versions_removed: number;
  bytes_freed: number;
  files_affected: number;
}

export interface ServerStatus {
  disk_total_bytes: number;
  disk_free_bytes: number;
  users: number;
  files: number;
  versions: number;
  logical_bytes: number;
  stored_bytes: number;
  uploads_in_progress: number;
  index_pending: number;
  index_failed: number;
  registration_mode: string;
  gc_delete_enabled: boolean;
}

export interface LoginEvent {
  at: string;
  ip: string;
  user_agent: string;
  success: boolean;
  new_device: boolean;
}

export const getSpace = () => apiGet<SpaceReport>("/api/insights/space");
export const pruneVersions = (keep: number, dryRun: boolean) =>
  apiPost<PruneReport>("/api/insights/prune-versions", { keep, dry_run: dryRun });
export const getServerStatus = () => apiGet<ServerStatus>("/api/admin/server");
export const getSecurityLog = () => apiGet<LoginEvent[]>("/api/auth/security-log");
