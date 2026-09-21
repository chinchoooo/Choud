import { apiGet } from "./client";
import type { HealthResponse } from "../types/health";

export function fetchHealth(): Promise<HealthResponse> {
  return apiGet<HealthResponse>("/api/health");
}
