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
  created_at: string;
  updated_at: string;
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
