import { apiGet, apiPost } from "./client";

export interface TwoFactorStatus {
  enabled: boolean;
  recovery_codes_left: number;
}

export interface TwoFactorSetup {
  secret: string;
  otpauth_uri: string;
}

export const getTwoFactorStatus = () => apiGet<TwoFactorStatus>("/api/auth/2fa");
export const startTwoFactor = () => apiPost<TwoFactorSetup>("/api/auth/2fa/setup");
export const enableTwoFactor = (code: string) =>
  apiPost<{ recovery_codes: string[] }>("/api/auth/2fa/enable", { code });
export const newRecoveryCodes = (code: string) =>
  apiPost<{ recovery_codes: string[] }>("/api/auth/2fa/recovery-codes", { code });
export const disableTwoFactor = (password: string, code: string) =>
  apiPost<void>("/api/auth/2fa/disable", { password, code });
