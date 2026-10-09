export interface VersionResponse {
  id: string;
  file_id: string;
  version_number: number;
  content_hash: string;
  size: number;
  // Number of the older version this one copied, or null for a normal upload.
  restored_from_version: number | null;
  created_by: string;
  created_at: string;
  is_current: boolean;
}

export interface VersionListResponse {
  file_id: string;
  // Newest first.
  versions: VersionResponse[];
}
