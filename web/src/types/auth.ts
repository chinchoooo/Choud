export interface User {
  id: string;
  username: string;
  email: string;
  is_active: boolean;
  storage_quota: number;
  totp_enabled?: boolean;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}
