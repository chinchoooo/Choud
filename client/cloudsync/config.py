"""Client configuration: server address, sync folder and login tokens.

Stored as JSON in the user's config directory (not inside the sync folder, so
the tokens are never synced) with owner-only permissions, because it holds a
refresh token.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

MIB = 1024 * 1024


def default_config_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "CloudSync"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "CloudSync"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "cloudsync"


@dataclass
class Config:
    server_url: str = ""
    email: str = ""
    sync_root: str = ""
    access_token: str = ""
    refresh_token: str = ""
    # Seconds between full syncs when nothing local changed (server changes are
    # found by polling).
    poll_interval: float = 30.0
    # Seconds of quiet after the last filesystem event before syncing, and how
    # recently a file may have been modified and still be considered "being
    # written" (such files are skipped until they settle).
    debounce_seconds: float = 2.0
    settle_seconds: float = 2.0
    # Files larger than this use the resumable chunked upload.
    chunk_threshold: int = 20 * MIB
    chunk_size: int = 5 * MIB
    extra: dict = field(default_factory=dict)

    @property
    def root(self) -> Path:
        return Path(self.sync_root)

    @property
    def state_dir(self) -> Path:
        return self.root / ".cloudsync"

    @property
    def is_logged_in(self) -> bool:
        return bool(self.server_url and self.refresh_token)


def config_path(config_dir: Path | None = None) -> Path:
    return (config_dir or default_config_dir()) / "config.json"


def load_config(config_dir: Path | None = None) -> Config:
    path = config_path(config_dir)
    if not path.exists():
        return Config()
    data = json.loads(path.read_text(encoding="utf-8"))
    known = {k: v for k, v in data.items() if k in Config.__dataclass_fields__}
    return Config(**known)


def save_config(config: Config, config_dir: Path | None = None) -> Path:
    path = config_path(config_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write to a temp file with restrictive permissions, then rename, so the
    # tokens are never visible to other users and a crash can't truncate the file.
    tmp = path.with_suffix(".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(asdict(config), handle, indent=2)
    os.replace(tmp, path)
    return path
