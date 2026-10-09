import { apiGet, apiPost } from "./client";
import { downloadAuthenticated } from "./files";
import type { VersionListResponse, VersionResponse } from "../types/versions";

export function listVersions(fileId: string): Promise<VersionListResponse> {
  return apiGet<VersionListResponse>(`/api/files/${fileId}/versions`);
}

// Restoring appends a *new* version that copies the old content; the version
// you restored from stays in the history.
export function restoreVersion(fileId: string, versionId: string): Promise<VersionResponse> {
  return apiPost<VersionResponse>(`/api/files/${fileId}/versions/${versionId}/restore`);
}

export function downloadVersion(
  fileId: string,
  versionId: string,
  filename: string,
): Promise<void> {
  return downloadAuthenticated(`/api/files/${fileId}/versions/${versionId}/download`, filename);
}
