import { apiGet, apiPost } from "./client";

export interface PastFile {
  id: string;
  name: string;
  mime_type: string | null;
  size: number;
  version_number: number;
  version_at: string;
  /** Today's content differs from what it was at the chosen time. */
  changed: boolean;
  /** The file is in the trash today. */
  trashed: boolean;
}

export interface PastFolder {
  id: string;
  name: string;
}

export interface PastListing {
  at: string;
  folder_id: string | null;
  folder_name: string | null;
  folders: PastFolder[];
  files: PastFile[];
}

export interface RewindReport {
  dry_run: boolean;
  restored_content: number;
  undeleted: number;
  unchanged: number;
  newer_untouched: number;
  files: string[];
}

export const browsePast = (at: string, folderId: string | null) =>
  apiGet<PastListing>(`/api/rewind/browse?at=${encodeURIComponent(at)}${folderId ? `&folder_id=${folderId}` : ""}`);

export const restorePastFile = (fileId: string, at: string) =>
  apiPost<RewindReport>("/api/rewind/restore-file", { file_id: fileId, at });

export const restorePastTree = (folderId: string | null, at: string, dryRun: boolean) =>
  apiPost<RewindReport>("/api/rewind/restore-tree", { folder_id: folderId, at, dry_run: dryRun });
