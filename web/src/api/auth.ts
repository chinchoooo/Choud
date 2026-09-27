import { apiGet, apiPost } from "./client";
import type { TokenResponse, User } from "../types/auth";

export interface RegisterInput {
  username: string;
  email: string;
  password: string;
}

export interface LoginInput {
  email: string;
  password: string;
}

export function register(input: RegisterInput): Promise<User> {
  return apiPost<User>("/api/auth/register", input);
}

export function login(input: LoginInput): Promise<TokenResponse> {
  return apiPost<TokenResponse>("/api/auth/login", input);
}

export function fetchMe(): Promise<User> {
  return apiGet<User>("/api/auth/me");
}

export function logout(): Promise<void> {
  return apiPost<void>("/api/auth/logout");
}
