"""Pull searchable text out of a file (Phase 14).

Plain-text types are read directly. PDFs and Office/OpenDocument files are parsed in a **separate,
resource-limited process** (`python -m app.services.text_extract <kind> <path>`): these formats are
complicated, anyone with an edit link can upload one, and a hostile file must only ever be able to
hurt a throwaway subprocess (killed after a timeout, memory-capped on Linux), never the API.
"""

import re
import subprocess
import sys
import zipfile
from pathlib import Path

MAX_TEXT_CHARS = 1_000_000  # kept per file; enough for a long book, bounded for the database
MAX_PLAIN_BYTES = 5 * 1024 * 1024
MAX_PARSED_BYTES = 40 * 1024 * 1024  # PDFs / Office files larger than this are not indexed
MAX_ZIP_PART_BYTES = 30 * 1024 * 1024  # uncompressed size of one XML part (zip-bomb guard)
MAX_PDF_PAGES = 200
SUBPROCESS_TIMEOUT = 60
MEMORY_LIMIT_BYTES = 1024 * 1024 * 1024

PLAIN_EXTENSIONS = frozenset(
    "txt md markdown rst log csv tsv json jsonl yaml yml toml ini cfg conf env xml html htm css "
    "js mjs ts tsx jsx py rb go rs java kt kts c h cpp hpp cc cs php sh bash zsh bat ps1 sql "
    "tex bib srt vtt gradle properties".split()
)
PLAIN_MIME_PREFIXES = ("text/",)
PLAIN_MIME_EXACT = frozenset(
    {
        "application/json",
        "application/xml",
        "application/x-yaml",
        "application/javascript",
        "application/x-sh",
        "application/sql",
    }
)
ZIP_EXTENSIONS = {
    "docx": "word/",
    "pptx": "ppt/slides/",
    "odt": "content.xml",
    "ods": "content.xml",
}

_TAG = re.compile(r"<[^>]+>")
_BREAKS = re.compile(r"</(?:w:p|a:p|text:p|text:h|table:table-row)>")
_SPACE = re.compile(r"[ \t\r\f\v]+")
_BLANKS = re.compile(r"\n\s*\n+")


def _extension(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def kind_of(name: str, mime: str | None) -> str | None:
    """ "plain", "pdf", "zipxml", or None when there is nothing to extract."""
    ext = _extension(name)
    mime = (mime or "").split(";")[0].strip().lower()
    if ext == "pdf" or mime == "application/pdf":
        return "pdf"
    if ext in ZIP_EXTENSIONS:
        return "zipxml"
    if ext in PLAIN_EXTENSIONS or mime.startswith(PLAIN_MIME_PREFIXES) or mime in PLAIN_MIME_EXACT:
        return "plain"
    return None


def _clean(text: str) -> str:
    text = text.replace("\x00", "")
    text = _SPACE.sub(" ", text)
    text = _BLANKS.sub("\n\n", text)
    return text.strip()[:MAX_TEXT_CHARS]


def extract_plain(path: Path) -> str | None:
    """The text of a text-like file, or None if it turns out to be binary."""
    with path.open("rb") as handle:
        data = handle.read(MAX_PLAIN_BYTES)
    if b"\x00" in data[:8192]:
        return None  # a binary file with a text-looking name
    return _clean(data.decode("utf-8", errors="replace"))


def extract_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path), strict=False)
    if reader.is_encrypted:
        return ""
    parts: list[str] = []
    total = 0
    for page in reader.pages[:MAX_PDF_PAGES]:
        try:
            text = page.extract_text() or ""
        except Exception:  # one unreadable page must not lose the rest
            continue
        parts.append(text)
        total += len(text)
        if total >= MAX_TEXT_CHARS:
            break
    return _clean("\n\n".join(parts))


def extract_zipxml(path: Path, ext: str) -> str:
    """Text of a .docx/.pptx/.odt/.ods: strip the tags from the XML parts that hold the content."""
    wanted = ZIP_EXTENSIONS.get(ext, "")
    chunks: list[str] = []
    total = 0
    with zipfile.ZipFile(path) as archive:
        names = [n for n in archive.namelist() if n == wanted or n.startswith(wanted)]
        for name in sorted(names)[:500]:
            if not name.endswith(".xml"):
                continue
            info = archive.getinfo(name)
            if info.file_size > MAX_ZIP_PART_BYTES:
                continue
            with archive.open(name) as part:
                xml = part.read(MAX_ZIP_PART_BYTES + 1)
            if len(xml) > MAX_ZIP_PART_BYTES:
                continue
            text = _TAG.sub("", _BREAKS.sub("\n", xml.decode("utf-8", errors="replace")))
            text = (
                text.replace("&amp;", "&")
                .replace("&lt;", "<")
                .replace("&gt;", ">")
                .replace("&quot;", '"')
                .replace("&apos;", "'")
            )
            chunks.append(text)
            total += len(text)
            if total >= MAX_TEXT_CHARS:
                break
    return _clean("\n".join(chunks))


def _limit_resources() -> None:  # pragma: no cover - runs in the child on Linux only
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (SUBPROCESS_TIMEOUT, SUBPROCESS_TIMEOUT))


def extract_text(path: Path, name: str, mime: str | None, size: int) -> str | None:
    """The searchable text of a stored file, "" if it has none, or None if the type is not indexed.

    Raises on a damaged or hostile file (the caller records that and moves on).
    """
    kind = kind_of(name, mime)
    if kind is None:
        return None
    if kind == "plain":
        return extract_plain(path)
    if size > MAX_PARSED_BYTES:
        return None
    # The file is staged under a neutral name so the child sees the right extension.
    command = [sys.executable, "-m", "app.services.text_extract", kind, str(path)]
    if kind == "zipxml":
        command.append(_extension(name))
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell; the path is ours
        command,
        capture_output=True,
        cwd=Path(__file__).resolve().parents[2],  # so `-m app...` finds the package
        timeout=SUBPROCESS_TIMEOUT,
        check=False,
        preexec_fn=_limit_resources if sys.platform.startswith("linux") else None,  # noqa: PLW1509
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip().splitlines()[-1:]
        raise ValueError(f"could not read the file: {detail[0] if detail else 'parser failed'}")
    return result.stdout[: MAX_TEXT_CHARS * 4].decode("utf-8", errors="replace")


def _worker(argv: list[str]) -> int:  # pragma: no cover - exercised through a subprocess
    kind, path = argv[0], Path(argv[1])
    text = extract_pdf(path) if kind == "pdf" else extract_zipxml(path, argv[2])
    sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_worker(sys.argv[1:]))
