import { apiDelete, apiGet, apiPost } from "./client";

export interface Invite {
  id: string;
  code: string;
  note: string | null;
  storage_quota: number | null;
  expires_at: string | null;
  used_at: string | null;
  created_at: string;
}

export interface RegistrationInfo {
  mode: "invite" | "open" | "closed";
  open: boolean;
  invite_required: boolean;
  first_account: boolean;
}

export const getRegistrationInfo = () => apiGet<RegistrationInfo>("/api/auth/registration");
export const listInvites = () => apiGet<Invite[]>("/api/invites");
export const deleteInvite = (id: string) => apiDelete<void>(`/api/invites/${id}`);
export const createInvite = (input: { note?: string; quotaGiB?: number }) =>
  apiPost<Invite>("/api/invites", {
    ...(input.note ? { note: input.note } : {}),
    ...(input.quotaGiB ? { storage_quota_bytes: Math.round(input.quotaGiB * 1024 ** 3) } : {}),
  });
