import type { FileResponse } from "../types/files";

export type ViewerKind = "image" | "video" | "audio" | "pdf" | "text" | "other";

// Formats the browser can show natively. Anything else falls back to "download".
const IMAGE_EXT = new Set(["png", "jpg", "jpeg", "gif", "webp", "avif", "bmp"]);
const VIDEO_EXT = new Set(["mp4", "webm", "mov", "m4v", "ogv", "mkv"]);
const AUDIO_EXT = new Set(["mp3", "m4a", "aac", "ogg", "oga", "wav", "flac", "opus"]);
const TEXT_EXT = new Set([
  "txt", "md", "markdown", "log", "csv", "tsv", "json", "yaml", "yml", "toml", "ini", "cfg",
  "conf", "env", "xml", "html", "htm", "css", "js", "mjs", "ts", "tsx", "jsx", "py", "rb", "go",
  "rs", "java", "kt", "c", "h", "cpp", "hpp", "cs", "sh", "bash", "ps1", "bat", "sql", "tex",
]);

// Mirrors the server's inline allowlist (server/app/api/media.py). SVG and HTML are
// deliberately absent: the server never serves them inline, so they are shown as text.
const SERVER_INLINE = new Set([
  "image/png", "image/jpeg", "image/gif", "image/webp", "image/avif", "image/bmp",
  "application/pdf", "text/plain",
  "video/mp4", "video/webm", "video/quicktime", "video/ogg", "video/x-matroska",
  "audio/mpeg", "audio/mp4", "audio/aac", "audio/ogg", "audio/wav", "audio/x-wav",
  "audio/webm", "audio/flac",
]);

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot <= 0 ? "" : name.slice(dot + 1).toLowerCase();
}

export function viewerKind(file: Pick<FileResponse, "name" | "mime_type">): ViewerKind {
  const mime = (file.mime_type ?? "").split(";")[0].trim().toLowerCase();
  const ext = extensionOf(file.name);

  // Only trust a media/pdf type if the server will really serve it inline.
  if (SERVER_INLINE.has(mime)) {
    if (mime.startsWith("image/")) return "image";
    if (mime.startsWith("video/")) return "video";
    if (mime.startsWith("audio/")) return "audio";
    if (mime === "application/pdf") return "pdf";
  }
  if (mime === "text/plain" || TEXT_EXT.has(ext) || mime.startsWith("text/")) return "text";
  if (mime === "application/json" || mime === "application/xml") return "text";
  // Unknown or generic mime type: fall back on the extension.
  if (IMAGE_EXT.has(ext) && !mime.startsWith("image/svg")) return "image";
  if (VIDEO_EXT.has(ext)) return "video";
  if (AUDIO_EXT.has(ext)) return "audio";
  if (ext === "pdf") return "pdf";
  return "other";
}

/** A small label for file-type badges, e.g. "PDF", "MP4", "DIR". */
export function typeBadge(file: Pick<FileResponse, "name">): string {
  const ext = extensionOf(file.name);
  return (ext || "file").slice(0, 4).toUpperCase();
}
