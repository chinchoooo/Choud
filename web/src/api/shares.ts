import { apiDelete, apiGet, apiPatch, apiPost } from "./client";

export interface Share {
  id: string;
  kind: "file" | "folder";
  target_id: string;
  target_name: string;
  token: string;
  url_path: string;
  label: string | null;
  has_password: boolean;
  permission: "view" | "edit" | "drop";
  max_downloads: number | null;
  expires_at: string | null;
  created_at: string;
  download_count: number;
  last_accessed_at: string | null;
  active: boolean;
}

export interface CreateShareInput {
  fileId?: string;
  folderId?: string;
  /** null/undefined = the link never expires on its own. */
  expiresInHours?: number | null;
  password?: string;
  label?: string;
  permission?: "view" | "edit" | "drop";
  /** The link stops working after this many downloads (1 = a one-time link). */
  maxDownloads?: number;
}

export function createShare(input: CreateShareInput): Promise<Share> {
  return apiPost<Share>("/api/shares", {
    ...(input.fileId ? { file_id: input.fileId } : {}),
    ...(input.folderId ? { folder_id: input.folderId } : {}),
    ...(input.expiresInHours ? { expires_in_hours: input.expiresInHours } : {}),
    ...(input.password ? { password: input.password } : {}),
    ...(input.label ? { label: input.label } : {}),
    ...(input.permission ? { permission: input.permission } : {}),
    ...(input.maxDownloads ? { max_downloads: input.maxDownloads } : {}),
  });
}

export function listShares(): Promise<Share[]> {
  return apiGet<Share[]>("/api/shares");
}

export function updateShare(
  id: string,
  changes: { password?: string | null; expiresInHours?: number | null; label?: string | null; permission?: "view" | "edit" | "drop"; maxDownloads?: number | null },
): Promise<Share> {
  return apiPatch<Share>(`/api/shares/${id}`, {
    ...("password" in changes ? { password: changes.password } : {}),
    ...("expiresInHours" in changes ? { expires_in_hours: changes.expiresInHours } : {}),
    ...("label" in changes ? { label: changes.label } : {}),
    ...("permission" in changes ? { permission: changes.permission } : {}),
    ...("maxDownloads" in changes ? { max_downloads: changes.maxDownloads } : {}),
  });
}

export function revokeShare(id: string): Promise<void> {
  return apiDelete<void>(`/api/shares/${id}`);
}

/** The full address to hand to someone: this site's origin plus the link's path. */
export function shareUrl(share: Pick<Share, "url_path">, origin = window.location.origin): string {
  return `${origin}${share.url_path}`;
}

export const DOWNLOAD_LIMITS: { label: string; count: number | null }[] = [
  { label: "No limit", count: null },
  { label: "Once (a one-time link)", count: 1 },
  { label: "5 downloads", count: 5 },
  { label: "25 downloads", count: 25 },
  { label: "100 downloads", count: 100 },
];

export const EXPIRY_CHOICES: { label: string; hours: number | null }[] = [
  { label: "Never", hours: null },
  { label: "1 hour", hours: 1 },
  { label: "1 day", hours: 24 },
  { label: "7 days", hours: 24 * 7 },
  { label: "30 days", hours: 24 * 30 },
];
