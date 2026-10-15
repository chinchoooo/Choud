"""Thumbnails for images and videos (Milestone 2).

Thumbnails are derived data: generated on first request from the stored object,
cached under `${STORAGE_ROOT}/thumbs/` keyed by content hash + size (so two files
with the same bytes share one), and safe to delete at any time.
"""

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.core.config import get_settings
from app.models.file import File
from app.services import file_service

logger = logging.getLogger(__name__)
settings = get_settings()

ALLOWED_SIZES = (128, 256, 512, 1024)
# Refuse to decode absurdly large images (decompression bombs) or run ffmpeg on huge inputs.
MAX_IMAGE_PIXELS = 120_000_000


class ThumbnailUnavailable(Exception):
    """This kind of file has no thumbnail (unsupported type, or it could not be decoded)."""


def thumbs_dir() -> Path:
    return Path(settings.storage_root) / "thumbs"


def kind_of(file: File) -> str | None:
    mime = (file.mime_type or "").lower()
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    return None


def _image_thumbnail(source: Path, target: Path, size: int) -> None:
    from PIL import Image, ImageOps

    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image)
        image.thumbnail((size, size))
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        image.save(target, "JPEG", quality=82, optimize=True)


def _video_thumbnail(source: Path, target: Path, size: int) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise ThumbnailUnavailable("ffmpeg is not installed on the server")
    scale = f"scale='min({size},iw)':'min({size},ih)':force_original_aspect_ratio=decrease"
    # Try a frame one second in; very short clips fall back to the first frame.
    for seek in ("1", "0"):
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell, paths are ours
            [
                ffmpeg, "-v", "error", "-y", "-ss", seek, "-i", str(source),
                "-frames:v", "1", "-vf", scale, "-q:v", "4", str(target),
            ],
            capture_output=True,
            timeout=60,
            check=False,
        )
        if result.returncode == 0 and target.exists() and target.stat().st_size > 0:
            return
    raise ThumbnailUnavailable("could not extract a frame from the video")


def get_thumbnail(file: File, size: int) -> Path:
    """Path of a JPEG thumbnail at most `size` px on its longest side (generated if needed)."""
    if size not in ALLOWED_SIZES:
        raise ThumbnailUnavailable(f"size must be one of {ALLOWED_SIZES}")
    kind = kind_of(file)
    if kind is None or not file.content_hash:
        raise ThumbnailUnavailable("no thumbnail for this type of file")

    directory = thumbs_dir()
    directory.mkdir(parents=True, exist_ok=True)
    cached = directory / f"{file.content_hash}-{size}.jpg"
    if cached.exists():
        return cached

    staged = file_service.prepare_download(file)
    fd, tmp_name = tempfile.mkstemp(dir=directory, suffix=".tmp.jpg")
    os.close(fd)  # we only want a unique name; Pillow/ffmpeg reopen it
    tmp_out = Path(tmp_name)
    try:
        if kind == "image":
            _image_thumbnail(staged, tmp_out, size)
        else:
            _video_thumbnail(staged, tmp_out, size)
        tmp_out.replace(cached)  # atomic: a half-written thumbnail is never served
    except ThumbnailUnavailable:
        tmp_out.unlink(missing_ok=True)
        raise
    except Exception as exc:
        tmp_out.unlink(missing_ok=True)
        logger.warning("thumbnail failed for %s: %s", file.id, exc)
        raise ThumbnailUnavailable(f"could not create a thumbnail: {exc}") from exc
    finally:
        staged.unlink(missing_ok=True)
    return cached
