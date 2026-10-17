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
  permission: "view" | "edit";
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
  permission?: "view" | "edit";
}

export function createShare(input: CreateShareInput): Promise<Share> {
  return apiPost<Share>("/api/shares", {
    ...(input.fileId ? { file_id: input.fileId } : {}),
    ...(input.folderId ? { folder_id: input.folderId } : {}),
    ...(input.expiresInHours ? { expires_in_hours: input.expiresInHours } : {}),
    ...(input.password ? { password: input.password } : {}),
    ...(input.label ? { label: input.label } : {}),
    ...(input.permission ? { permission: input.permission } : {}),
  });
}

export function listShares(): Promise<Share[]> {
  return apiGet<Share[]>("/api/shares");
}

export function updateShare(
  id: string,
  changes: { password?: string | null; expiresInHours?: number | null; label?: string | null; permission?: "view" | "edit" },
): Promise<Share> {
  return apiPatch<Share>(`/api/shares/${id}`, {
    ...("password" in changes ? { password: changes.password } : {}),
    ...("expiresInHours" in changes ? { expires_in_hours: changes.expiresInHours } : {}),
    ...("label" in changes ? { label: changes.label } : {}),
    ...("permission" in changes ? { permission: changes.permission } : {}),
  });
}

export function revokeShare(id: string): Promise<void> {
  return apiDelete<void>(`/api/shares/${id}`);
}

/** The full address to hand to someone: this site's origin plus the link's path. */
export function shareUrl(share: Pick<Share, "url_path">, origin = window.location.origin): string {
  return `${origin}${share.url_path}`;
}

export const EXPIRY_CHOICES: { label: string; hours: number | null }[] = [
  { label: "Never", hours: null },
  { label: "1 hour", hours: 1 },
  { label: "1 day", hours: 24 },
  { label: "7 days", hours: 24 * 7 },
  { label: "30 days", hours: 24 * 30 },
];
