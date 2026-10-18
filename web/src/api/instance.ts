import { apiGet, apiPost, apiPut } from "./client";

export interface InstanceInfo {
  version: string;
  public_base_url: string | null;
  public_status: "ready" | "paused" | "not_configured";
  public_door_mode: string;
  is_admin: boolean;
}

export interface PublicCheck {
  ok: boolean;
  detail: string;
  door: string | null;
  client_ip: string | null;
}

export const getInstance = () => apiGet<InstanceInfo>("/api/instance");
export const setPublicLinks = (enabled: boolean) => apiPut<InstanceInfo>("/api/admin/public-links", { enabled });
export const checkPublicLinks = () => apiPost<PublicCheck>("/api/admin/public-links/check", {});
export const revokeAllShares = () => apiPost<{ revoked: number }>("/api/shares/revoke-all", {});
