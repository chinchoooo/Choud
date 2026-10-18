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
from app.services.storage_service import get_storage_service

logger = logging.getLogger(__name__)
settings = get_settings()

ALLOWED_SIZES = (128, 256, 512, 1024)
FORMATS = {"jpg": "image/jpeg", "webp": "image/webp"}
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


def _image_thumbnail(source: Path, target: Path, size: int, fmt: str = "jpg") -> None:
    from PIL import Image, ImageOps

    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    with Image.open(source) as image:
        # For JPEG, let the decoder shrink while reading: a 50-megapixel photo then never has to
        # exist at full size in memory just to make a 256px thumbnail.
        image.draft("RGB", (size * 2, size * 2))
        image = ImageOps.exif_transpose(image)
        image.thumbnail((size, size))
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        if fmt == "webp":
            # About a third smaller than JPEG at the same look, which is most of the bytes on a
            # slow link. method=4 is the usual speed/size balance.
            image.save(target, "WEBP", quality=72, method=4)
        else:
            image.save(target, "JPEG", quality=82, optimize=True)


def _to_webp(jpeg: Path, target: Path) -> None:
    """Re-encodes a (small) JPEG thumbnail as WebP (video frames come out of ffmpeg as JPEG)."""
    from PIL import Image

    with Image.open(jpeg) as image:
        image.convert("RGB").save(target, "WEBP", quality=72, method=4)


def sniff_container(path: Path) -> str | None:
    """The ffmpeg demuxer for a real MP4/MOV or Matroska/WebM file, judged by its first bytes.

    The extension and MIME type are the uploader's claim and mean nothing. ffmpeg's own format
    detection would also happily open playlists and concat scripts that point at other files or
    URLs, so ffmpeg is only ever pointed at a file whose bytes prove it is one of these two.
    """
    try:
        with path.open("rb") as handle:
            head = handle.read(12)
    except OSError:
        return None
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return "mov"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "matroska"
    return None


def _video_thumbnail(source: Path, target: Path, size: int) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise ThumbnailUnavailable("ffmpeg is not installed on the server")
    demuxer = sniff_container(source)
    if demuxer is None:
        raise ThumbnailUnavailable("only MP4/MOV and WebM/MKV videos get thumbnails")
    scale = f"scale='min({size},iw)':'min({size},ih)':force_original_aspect_ratio=decrease"
    # Try a frame one second in; very short clips fall back to the first frame.
    for seek in ("1", "0"):
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell, paths are ours
            [
                ffmpeg, "-v", "error", "-y",
                "-protocol_whitelist", "file",  # never fetch anything over the network
                "-f", demuxer,  # the demuxer we verified, not whatever ffmpeg would guess
                "-ss", seek, "-i", str(source),
                "-frames:v", "1", "-vf", scale, "-q:v", "4", str(target),
            ],
            capture_output=True,
            timeout=60,
            check=False,
        )
        if result.returncode == 0 and target.exists() and target.stat().st_size > 0:
            return
    raise ThumbnailUnavailable("could not extract a frame from the video")


def get_thumbnail(file: File, size: int, fmt: str = "jpg") -> Path:
    """Path of a thumbnail at most `size` px on its longest side (generated if needed).

    `fmt` is "jpg" (works everywhere) or "webp" (smaller; every Android and browser we support).
    """
    if size not in ALLOWED_SIZES:
        raise ThumbnailUnavailable(f"size must be one of {ALLOWED_SIZES}")
    if fmt not in FORMATS:
        raise ThumbnailUnavailable(f"format must be one of {tuple(FORMATS)}")
    kind = kind_of(file)
    if kind is None or not file.content_hash:
        raise ThumbnailUnavailable("no thumbnail for this type of file")

    directory = thumbs_dir()
    directory.mkdir(parents=True, exist_ok=True)
    cached = directory / f"{file.content_hash}-{size}.{fmt}"
    if cached.exists():
        return cached
    if fmt == "webp" and kind == "video":
        # ffmpeg writes JPEG; make that first (cached for the JPEG callers too), then convert.
        jpeg = get_thumbnail(file, size, "jpg")
        tmp_webp = directory / f"{file.content_hash}-{size}.tmp.webp"
        _to_webp(jpeg, tmp_webp)
        tmp_webp.replace(cached)
        return cached

    # Read the stored object in place when we can (no copy of a multi-megabyte original just to
    # shrink it); otherwise fall back to asking the engine for a staged copy.
    staged: Path | None = None
    source = get_storage_service().local_path(file.content_hash)
    if source is None:
        staged = file_service.prepare_download(file)
        source = staged
    fd, tmp_name = tempfile.mkstemp(dir=directory, suffix=f".tmp.{fmt}")
    os.close(fd)  # we only want a unique name; Pillow/ffmpeg reopen it
    tmp_out = Path(tmp_name)
    try:
        if kind == "image":
            _image_thumbnail(source, tmp_out, size, fmt)
        else:
            _video_thumbnail(source, tmp_out, size)
        tmp_out.replace(cached)  # atomic: a half-written thumbnail is never served
    except ThumbnailUnavailable:
        tmp_out.unlink(missing_ok=True)
        raise
    except Exception as exc:
        tmp_out.unlink(missing_ok=True)
        logger.warning("thumbnail failed for %s: %s", file.id, exc)
        raise ThumbnailUnavailable(f"could not create a thumbnail: {exc}") from exc
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)
    return cached


# --- pre-generation -------------------------------------------------------------------------------

PREGENERATE_SIZE = 256  # what the photo grid and file lists ask for
_settled: set[str] = set()  # content hashes already done (or known impossible) in this process


def _marker(content_hash: str) -> Path:
    return thumbs_dir() / f"{content_hash}-{PREGENERATE_SIZE}.fail"


def pregenerate(db, limit: int = 6) -> int:
    """Makes grid thumbnails ahead of time for photos and videos that lack one, newest first.

    Opening Photos then finds them ready instead of making a whole screenful at once, which is
    the slow part. For each file it makes the JPEG and WebP grid thumbnails and the ThumbHash
    placeholder. Files that cannot have a thumbnail get a marker so they are not retried forever.
    Returns how many files it worked on.
    """
    from sqlalchemy import or_, select

    directory = thumbs_dir()
    directory.mkdir(parents=True, exist_ok=True)
    rows = db.execute(
        select(File)
        .where(
            File.deleted_at.is_(None),
            File.content_hash.is_not(None),
            or_(File.mime_type.like("image/%"), File.mime_type.like("video/%")),
        )
        .order_by(File.created_at.desc())
    ).scalars()
    made = 0
    dirty = False
    for file in rows:
        if made >= limit:
            break
        content_hash = file.content_hash
        if content_hash in _settled and file.thumbhash is not None:
            continue
        if _marker(content_hash).exists():
            _settled.add(content_hash)
            continue
        try:
            jpeg = get_thumbnail(file, PREGENERATE_SIZE, "jpg")
            get_thumbnail(file, PREGENERATE_SIZE, "webp")
            if file.thumbhash is None:
                file.thumbhash = _thumbhash_for(file, jpeg)
                dirty = True
            made += 1
        except (ThumbnailUnavailable, file_service.StorageError):
            _marker(content_hash).touch()
        except Exception as exc:  # one bad file must never stop the rest
            logger.warning("thumbnail pre-generation failed for %s: %s", file.id, exc)
            _marker(content_hash).touch()
        _settled.add(content_hash)
    if dirty:
        db.commit()
    return made


def _thumbhash_for(file: File, jpeg: Path) -> str | None:
    """The ThumbHash of a file, shared by every file with the same bytes."""
    from app.services import thumbhash

    # "" means "tried, nothing to show": it stops the file being retried on every pass.
    return thumbhash.thumbhash_of_image(jpeg) or ""
