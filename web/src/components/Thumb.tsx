import { useState } from "react";

import { useMedia } from "../media/MediaContext";
import { typeBadge, viewerKind } from "../lib/viewerKind";
import type { FileResponse } from "../types/files";

/** A boxed extension label ("PDF", "MP4") used wherever there is no thumbnail. */
export function FileBadge({ file, className = "" }: { file: Pick<FileResponse, "name">; className?: string }) {
  return (
    <span
      className={`inline-flex items-center justify-center border border-gray-300 bg-gray-100 text-xs font-medium text-gray-600 ${className}`}
    >
      {typeBadge(file)}
    </span>
  );
}

export function FolderBadge({ className = "" }: { className?: string }) {
  return (
    <span
      className={`inline-flex items-center justify-center border border-gray-300 bg-gray-100 text-xs font-medium text-gray-600 ${className}`}
    >
      DIR
    </span>
  );
}

/**
 * A thumbnail for images and videos (generated and cached by the server), with a plain
 * badge for everything else or when the server can't make one.
 */
export function Thumb({
  file,
  size = 256,
  className = "h-10 w-10",
  fit = "cover",
}: {
  file: FileResponse;
  size?: 128 | 256 | 512 | 1024;
  className?: string;
  fit?: "cover" | "contain";
}) {
  const media = useMedia();
  const [failed, setFailed] = useState(false);
  const kind = viewerKind(file);
  const src = kind === "image" || kind === "video" ? media.thumbUrl(file.id, size) : null;

  if (!src || failed) {
    return <FileBadge file={file} className={className} />;
  }
  return (
    <span className={`relative inline-block overflow-hidden border border-gray-200 bg-gray-100 ${className}`}>
      <img
        src={src}
        alt=""
        loading="lazy"
        decoding="async"
        onError={() => setFailed(true)}
        className={`h-full w-full ${fit === "cover" ? "object-cover" : "object-contain"}`}
      />
      {kind === "video" && (
        <span className="absolute bottom-0.5 right-0.5 bg-black/70 px-1 text-[10px] leading-4 text-white">▶</span>
      )}
    </span>
  );
}
