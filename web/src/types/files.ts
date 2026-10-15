export interface FolderResponse {
  id: string;
  owner_id: string;
  parent_id: string | null;
  name: string;
  created_at: string;
  updated_at: string;
}

export interface FileResponse {
  id: string;
  owner_id: string;
  folder_id: string | null;
  name: string;
  mime_type: string | null;
  size: number;
  content_hash: string | null;
  current_version_id?: string | null;
  /** When a photo/video was taken, if the uploading client knew. */
  taken_at?: string | null;
  created_at: string;
  updated_at: string;
  /** Filled in by the library routes and the directory listing. */
  is_favorite?: boolean;
  folder_path?: string | null;
}

export interface DirectoryListing {
  folder: FolderResponse | null;
  subfolders: FolderResponse[];
  files: FileResponse[];
}

export interface SearchResponse {
  folders: FolderResponse[];
  files: FileResponse[];
}

export interface PhotoPage {
  items: FileResponse[];
  total: number;
  offset: number;
  limit: number;
}

export interface Usage {
  used_bytes: number;
  quota_bytes: number;
  file_count: number;
}

export interface ActivityItem {
  id: string;
  action: string;
  file_id: string | null;
  file_name: string;
  detail: string | null;
  created_at: string;
}
