export interface UploadSessionResponse {
  id: string;
  file_name: string;
  file_size: number;
  chunk_size: number;
  total_chunks: number;
  status: string;
  created_at: string;
  expires_at: string;
}

export interface UploadStatusResponse extends UploadSessionResponse {
  received_chunk_indices: number[];
  missing_chunk_indices: number[];
}

export interface ChunkAckResponse {
  index: number;
  received: boolean;
  received_count: number;
  total_chunks: number;
}
