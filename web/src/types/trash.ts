export interface TrashedFileResponse {
  id: string;
  name: string;
  folder_id: string | null;
  mime_type: string | null;
  size: number;
  content_hash: string | null;
  deleted_at: string;
}

export interface TrashListResponse {
  // Most recently deleted first.
  files: TrashedFileResponse[];
}
