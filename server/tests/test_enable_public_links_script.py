"""scripts/enable-public-links.sh against pretend `tailscale`, `docker` and `curl`."""

import json
import os
import shutil
import subprocess
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
    BASH is None or shutil.which("python3") is None and shutil.which("python") is None,
    reason="needs bash and python3",
)

FAKE_DOCKER = """#!/usr/bin/env bash
echo "docker $*" >> "$FAKE_OUT/calls"
"""

# curl: the private door on 127.0.0.1 answers like the shares-only door; the public URL answers
# according to FAKE_PUBLIC (up | down).
FAKE_CURL = """#!/usr/bin/env bash
url="${@: -1}"
want_code=0
for a in "$@"; do [ "$a" = "%{http_code}" ] && want_code=1; done
code=404
body='Not found'
case "$url" in
  http://127.0.0.1:*/s/_health)
    code=200; body='{"ok":true,"door":"private","client_ip":"127.0.0.1"}' ;;
  http://127.0.0.1:*/api/health) code=${FAKE_LOCAL_API:-404} ;;
  https://*/s/_health)
    if [ "${FAKE_PUBLIC:-up}" = up ]; then
      code=200; body='{"ok":true,"door":"public","client_ip":"203.0.113.5"}'
    else
      code=000
    fi ;;
  https://*/api/health) code=404 ;;
esac
if [ "$want_code" = 1 ]; then printf '%s' "$code"; else printf '%s' "$body"; fi
"""

TAILSCALE_STATUS = {
    "Self": {"DNSName": "arvismint.tail1234.ts.net."},
    "CertDomains": ["arvismint.tail1234.ts.net"],
}


def _shim(path: Path, name: str, body: str) -> None:
    (path / name).write_text(body, newline="\n")
    (path / name).chmod(0o755)


@pytest.fixture
def box(tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(REPO / "scripts", repo / "scripts")
    (repo / ".env").write_text("JWT_SECRET=x\nPUBLIC_BASE_URL=\nPUBLIC_DOOR_MODE=shares\n")
    out = tmp_path / "out"
    out.mkdir()
    shim = tmp_path / "bin"
    shim.mkdir()
    _shim(shim, "docker", FAKE_DOCKER)
    _shim(shim, "curl", FAKE_CURL)
    _shim(
        shim,
        "tailscale",
        "#!/usr/bin/env bash\n"
        'echo "tailscale $*" >> "$FAKE_OUT/calls"\n'
        'case "$1" in\n'
        f"  status) echo '{json.dumps(TAILSCALE_STATUS)}' ;;\n"
        '  funnel) [ "${FAKE_FUNNEL:-ok}" = ok ] || exit 1 ;;\n'
        "esac\n",
    )
    _shim(shim, "sleep", "#!/usr/bin/env bash\nexit 0\n")
    return repo, out, shim


def _run(box, *args, **env):
    repo, out, shim = box
    environment = {
        **os.environ,
        "PATH": f"{shim}{os.pathsep}{os.environ['PATH']}",
        "FAKE_OUT": str(out),
        "ENABLE_PUBLIC_SUDO": "",
        **env,
    }
    return subprocess.run(
        [BASH, "scripts/enable-public-links.sh", *args],
        cwd=repo,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _calls(box) -> str:
    log = box[1] / "calls"
    return log.read_text() if log.exists() else ""


def test_tailscale_success_sets_the_address_and_restarts_only_the_backend(box):
    result = _run(box)
    assert result.returncode == 0, result.stdout + result.stderr
    env = (box[0] / ".env").read_text()
    assert "PUBLIC_BASE_URL=https://arvismint.tail1234.ts.net\n" in env
    assert "JWT_SECRET=x" in env  # nothing else touched
    assert (box[0] / ".env.bak").exists()
    calls = _calls(box)
    assert "tailscale funnel --bg --https=443 http://127.0.0.1:8081" in calls
    assert "docker compose up -d --no-deps backend" in calls
    assert "share pages" in result.stdout or "Share links are now" in result.stdout


def test_dry_run_changes_nothing(box):
    result = _run(box, "--dry-run")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PUBLIC_BASE_URL=\n" in (box[0] / ".env").read_text()
    assert not (box[0] / ".env.bak").exists()
    assert "funnel" not in _calls(box) and "docker" not in _calls(box)


def test_funnel_not_allowed_needs_one_manual_step(box):
    result = _run(box, FAKE_FUNNEL="no")
    assert result.returncode == 2
    assert "access controls" in result.stderr
    assert "PUBLIC_BASE_URL=\n" in (box[0] / ".env").read_text()


def test_unreachable_address_does_not_switch_links_on(box):
    result = _run(box, FAKE_PUBLIC="down")
    assert result.returncode == 1
    assert "did not answer" in result.stderr
    assert "PUBLIC_BASE_URL=\n" in (box[0] / ".env").read_text()


def test_refuses_when_the_public_door_would_expose_the_api(box):
    result = _run(box, FAKE_LOCAL_API="200")
    assert result.returncode == 1
    assert "should be 404" in result.stderr
    assert "funnel" not in _calls(box)


def test_off_clears_the_address(box):
    (box[0] / ".env").write_text("JWT_SECRET=x\nPUBLIC_BASE_URL=https://old.example\n")
    result = _run(box, "--off")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PUBLIC_BASE_URL=\n" in (box[0] / ".env").read_text()
    assert "tailscale funnel --https=443 off" in _calls(box)
    assert "docker compose up -d --no-deps backend" in _calls(box)


def test_status_changes_nothing(box):
    result = _run(box, "--status")
    assert result.returncode == 0
    assert "PUBLIC_BASE_URL" in result.stdout
    assert "docker" not in _calls(box)


def test_cloudflare_needs_a_hostname(box):
    result = _run(box, "--cloudflare")
    assert result.returncode == 1
    assert "needs a hostname" in result.stderr
