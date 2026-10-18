import { API_BASE_URL, getAccessToken } from "../api/client";
import { deleteFile, listDirectory, uploadFile } from "../api/files";
import { createFolder } from "../api/folders";
import type { FileResponse } from "../types/files";

/** The ordinary server folder that holds the encrypted data. It is visible, but everything in it is sealed. */
export const VAULT_FOLDER = "Vault (encrypted)";
export const CONFIG_NAME = "vault.json";
export const MANIFEST_NAME = "manifest.cvault";
export const BLOB_SUFFIX = ".cvault";
/** Files are sealed in the browser's memory, so very large ones are refused rather than crashing the tab. */
export const MAX_VAULT_FILE_BYTES = 400 * 1024 * 1024;

export interface VaultItem {
  name: string;
  size: number;
  type: string;
  added: string;
}

export interface Manifest {
  version: 1;
  items: Record<string, VaultItem>;
}

export interface VaultListing {
  config: FileResponse | null;
  manifest: FileResponse | null;
  /** The sealed files by their random id (the file name without ".cvault"). */
  blobs: Map<string, FileResponse>;
}

export async function findVaultFolder(): Promise<string | null> {
  const root = await listDirectory(null);
  return root.subfolders.find((folder) => folder.name === VAULT_FOLDER)?.id ?? null;
}

export async function createVaultFolder(): Promise<string> {
  return (await createFolder(VAULT_FOLDER, null)).id;
}

export async function listVault(folderId: string): Promise<VaultListing> {
  const listing = await listDirectory(folderId);
  const blobs = new Map<string, FileResponse>();
  let config: FileResponse | null = null;
  let manifest: FileResponse | null = null;
  for (const file of listing.files) {
    if (file.name === CONFIG_NAME) config = file;
    else if (file.name === MANIFEST_NAME) manifest = file;
    else if (file.name.endsWith(BLOB_SUFFIX)) blobs.set(file.name.slice(0, -BLOB_SUFFIX.length), file);
  }
  return { config, manifest, blobs };
}

/** Downloads a stored file as raw bytes (the browser never sees it as anything but ciphertext). */
export async function readBytes(fileId: string): Promise<Uint8Array> {
  const token = getAccessToken();
  const response = await fetch(`${API_BASE_URL}/api/files/${fileId}/download`, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  if (!response.ok) throw new Error(`could not read the file (status ${response.status})`);
  return new Uint8Array(await response.arrayBuffer());
}

/** Stores bytes under `name` in the vault folder; a name that exists becomes a new version. */
export function writeBytes(folderId: string, name: string, bytes: Uint8Array, type = "application/octet-stream") {
  return uploadFile(new File([bytes as BlobPart], name, { type }), folderId);
}

export function removeStored(fileId: string): Promise<void> {
  return deleteFile(fileId); // goes to the server's trash like any file
}
