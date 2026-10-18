import { apiPost } from "../api/client";

/** A file to upload together with the folder path (relative to where it was dropped) it sits in. */
export interface TreeFile {
  file: File;
  /** "" for the top level, otherwise "Trip/Day 1" (no leading or trailing slash). */
  dir: string;
}

/** Files picked with `<input webkitdirectory>`: the browser reports each one's relative path. */
export function fromPickedFolder(files: File[]): TreeFile[] {
  return files.map((file) => {
    const relative = (file as File & { webkitRelativePath?: string }).webkitRelativePath ?? "";
    const parts = relative.split("/").filter(Boolean);
    return { file, dir: parts.slice(0, -1).join("/") };
  });
}

interface FsEntry {
  isFile: boolean;
  isDirectory: boolean;
  name: string;
  file?: (ok: (file: File) => void, fail: (error: unknown) => void) => void;
  createReader?: () => { readEntries: (ok: (entries: FsEntry[]) => void, fail: (e: unknown) => void) => void };
}

async function walk(entry: FsEntry, dir: string, out: TreeFile[], budget: { left: number }): Promise<void> {
  if (budget.left <= 0) return;
  if (entry.isFile && entry.file) {
    const file = await new Promise<File>((ok, fail) => entry.file!(ok, fail));
    budget.left -= 1;
    out.push({ file, dir });
  } else if (entry.isDirectory && entry.createReader) {
    const reader = entry.createReader();
    const here = dir ? `${dir}/${entry.name}` : entry.name;
    // readEntries returns results in batches; keep asking until it comes back empty.
    for (;;) {
      const batch = await new Promise<FsEntry[]>((ok, fail) => reader.readEntries(ok, fail));
      if (batch.length === 0) break;
      for (const child of batch) await walk(child, here, out, budget);
    }
  }
}

/** Everything dropped, including whole folders, flattened into files with their folder paths. */
export async function fromDrop(items: DataTransferItemList, limit = 5000): Promise<TreeFile[]> {
  const entries: FsEntry[] = [];
  for (const item of Array.from(items)) {
    const entry = (item as DataTransferItem & { webkitGetAsEntry?: () => FsEntry | null }).webkitGetAsEntry?.();
    if (entry) entries.push(entry);
  }
  const out: TreeFile[] = [];
  const budget = { left: limit };
  for (const entry of entries) await walk(entry, "", out, budget);
  return out;
}

/** Groups files by folder so each folder is created once. */
export function groupByDir(files: TreeFile[]): Map<string, File[]> {
  const groups = new Map<string, File[]>();
  for (const { file, dir } of files) {
    groups.set(dir, [...(groups.get(dir) ?? []), file]);
  }
  return groups;
}

/** Makes sure a folder path exists on the server (creating what is missing); returns its id. */
export async function ensureFolderPath(path: string): Promise<string> {
  const result = await apiPost<{ id: string }>("/api/sync/folders", { path });
  return result.id;
}
