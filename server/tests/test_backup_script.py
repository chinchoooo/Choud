"""scripts/backup.sh and restore.sh with encryption, run against a pretend `docker`."""

import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _find_bash() -> str | None:
    found = shutil.which("bash")
    if found and "system32" not in found.lower():
        return found
    for candidate in ("C:/Program Files/Git/bin/bash.exe", "C:/Program Files/Git/usr/bin/bash.exe"):
        if Path(candidate).exists():
            return candidate
    return None


BASH = _find_bash()
pytestmark = pytest.mark.skipif(
    BASH is None or shutil.which("openssl") is None or shutil.which("tar") is None,
    reason="needs bash, openssl and tar",
)

FAKE_DOCKER = """#!/usr/bin/env bash
# A stand-in for `docker compose ...` that behaves like the real containers closely enough.
case "$*" in
  *pg_dump*) printf 'CREATE TABLE files();\\n-- PostgreSQL database dump complete\\n' ;;
  *"engine tar"*) tar -C "$FAKE_STORAGE" -cf - . ;;
  *"DROP SCHEMA"*) echo dropped >> "$FAKE_OUT/events" ;;
  *psql*) cat > "$FAKE_OUT/restored.sql" ;;
  *"engine sh -c"*) mkdir -p "$FAKE_OUT/restored" && tar -C "$FAKE_OUT/restored" -xf - ;;
  *stop*) echo stopped >> "$FAKE_OUT/events" ;;
  *) : ;;
esac
"""


@pytest.fixture
def sandbox(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(REPO / "scripts", root / "scripts")
    (root / ".env").write_text("JWT_SECRET=super-secret-value-123\nPOSTGRES_PASSWORD=pw\n")
    storage = tmp_path / "storage"
    (storage / "objects" / "ab").mkdir(parents=True)
    (storage / "objects" / "ab" / "abcdef").write_bytes(b"object bytes " * 100)
    out = tmp_path / "out"
    out.mkdir()
    shim = tmp_path / "bin"
    shim.mkdir()
    (shim / "docker").write_text(FAKE_DOCKER, newline="\n")
    (shim / "docker").chmod(0o755)
    passphrase = tmp_path / "passphrase"
    passphrase.write_text("correct horse battery staple\n")
    other = tmp_path / "other"
    other.write_text("a different passphrase\n")
    env = {
        **os.environ,
        "PATH": f"{shim.as_posix()}{os.pathsep}{os.environ['PATH']}",
        "FAKE_STORAGE": storage.as_posix(),
        "FAKE_OUT": out.as_posix(),
        "POSTGRES_USER": "cloud",
    }
    env.pop("BACKUP_PASSPHRASE_FILE", None)
    return {"root": root, "env": env, "out": out, "pass": passphrase, "other": other}


def _run(sandbox, script, *args, passphrase=None):
    env = dict(sandbox["env"])
    if passphrase is not None:
        env["BACKUP_PASSPHRASE_FILE"] = Path(passphrase).as_posix()
    return subprocess.run(
        [BASH, str(sandbox["root"] / "scripts" / script), *args],
        cwd=sandbox["root"],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _only_backup(sandbox) -> Path:
    found = sorted(p for p in (sandbox["root"] / "backups").iterdir() if p.name.startswith("2"))
    assert len(found) == 1, found
    return found[0]


def test_an_encrypted_backup_contains_no_plain_text_and_restores(sandbox) -> None:
    done = _run(sandbox, "backup.sh", passphrase=sandbox["pass"])
    assert done.returncode == 0, done.stderr
    backup = _only_backup(sandbox)

    names = sorted(p.name for p in backup.iterdir())
    assert names == [".env.enc", "ENCRYPTED", "SHA256SUMS", "database.sql.enc", "storage.tar.enc"]
    blob = b"".join(p.read_bytes() for p in backup.iterdir())
    for secret in (b"super-secret-value-123", b"CREATE TABLE", b"object bytes"):
        assert secret not in blob  # nothing readable without the passphrase

    restored = _run(sandbox, "restore.sh", str(backup), "--yes", passphrase=sandbox["pass"])
    assert restored.returncode == 0, restored.stderr
    assert "PostgreSQL database dump complete" in (sandbox["out"] / "restored.sql").read_text()
    assert (
        sandbox["out"] / "restored" / "objects" / "ab" / "abcdef"
    ).read_bytes() == b"object bytes " * 100


def test_without_a_passphrase_the_backup_is_plain_and_says_so(sandbox) -> None:
    done = _run(sandbox, "backup.sh")
    assert done.returncode == 0, done.stderr
    assert "NOT encrypted" in done.stderr
    backup = _only_backup(sandbox)
    assert (backup / "database.sql").exists() and not (backup / "ENCRYPTED").exists()
    assert _run(sandbox, "restore.sh", str(backup), "--yes").returncode == 0
    with tarfile.open(backup / "storage.tar") as archive:
        assert any(name.endswith("abcdef") for name in archive.getnames())


def test_a_wrong_or_missing_passphrase_changes_nothing(sandbox) -> None:
    _run(sandbox, "backup.sh", passphrase=sandbox["pass"])
    backup = _only_backup(sandbox)

    wrong = _run(sandbox, "restore.sh", str(backup), "--yes", passphrase=sandbox["other"])
    assert wrong.returncode != 0 and "nothing was changed" in wrong.stderr
    missing = _run(sandbox, "restore.sh", str(backup), "--yes")
    assert missing.returncode != 0 and "encrypted" in missing.stderr
    assert not (sandbox["out"] / "events").exists()  # never stopped, never dropped
    assert not (sandbox["out"] / "restored.sql").exists()


def test_a_damaged_encrypted_backup_is_refused(sandbox) -> None:
    _run(sandbox, "backup.sh", passphrase=sandbox["pass"])
    backup = _only_backup(sandbox)
    damaged = backup / "storage.tar.enc"
    data = bytearray(damaged.read_bytes())
    data[100] ^= 0xFF
    damaged.write_bytes(bytes(data))
    refused = _run(sandbox, "restore.sh", str(backup), "--yes", passphrase=sandbox["pass"])
    assert refused.returncode != 0 and "damaged" in refused.stderr
    assert not (sandbox["out"] / "events").exists()


def test_a_missing_passphrase_file_stops_the_backup_early(sandbox, tmp_path) -> None:
    done = _run(sandbox, "backup.sh", passphrase=tmp_path / "does-not-exist")
    assert done.returncode != 0 and "missing or empty" in done.stderr
    assert not (sandbox["root"] / "backups").exists() or not list(
        (sandbox["root"] / "backups").iterdir()
    )
