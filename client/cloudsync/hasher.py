"""SHA-256 of a file, streamed in bounded chunks.

The client only needs the same SHA-256 the server stores (hashlib is fine here;
the C++ engine is server-side only).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

CHUNK_BYTES = 1024 * 1024


def sha256_file(path: Path) -> str:
    """Hex SHA-256 of the file's bytes without loading it into memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()
