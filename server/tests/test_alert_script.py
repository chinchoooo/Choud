"""scripts/lib/notify.sh: alerts speak on changes only and never break the calling script."""

import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
NOTIFY = REPO / "scripts" / "lib" / "notify.sh"


def _find_bash() -> str | None:
    """A real bash: on Windows `bash` on the PATH is often the WSL launcher, which is no use."""
    found = shutil.which("bash")
    if found and "system32" not in found.lower():
        return found
    for candidate in (
        "C:/Program Files/Git/bin/bash.exe",
        "C:/Program Files/Git/usr/bin/bash.exe",
    ):
        if Path(candidate).exists():
            return candidate
    return None


BASH = _find_bash()
pytestmark = pytest.mark.skipif(
    BASH is None or shutil.which("curl") is None, reason="needs bash and curl"
)


class _Hook(BaseHTTPRequestHandler):
    received: list = []

    def do_POST(self):  # noqa: N802 - http.server API
        body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
        _Hook.received.append({"path": self.path, "headers": dict(self.headers), "body": body})
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):  # silence
        pass


@pytest.fixture
def hook():
    _Hook.received = []
    server = HTTPServer(("127.0.0.1", 0), _Hook)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()


def _notify(url: str, state_dir: Path, key: str, status: str, title="T", message="M", **env):
    # Title and message travel in environment variables so quotes and newlines survive intact.
    script = (
        f'. "{NOTIFY.as_posix()}"; notify_event "$NT_KEY" "$NT_STATUS" "$NT_TITLE" "$NT_MESSAGE"'
    )
    environment = {
        "PATH": __import__("os").environ["PATH"],
        "ALERT_WEBHOOK_URL": url,
        "ALERT_STATE_DIR": state_dir.as_posix(),
        "NT_KEY": key,
        "NT_STATUS": status,
        "NT_TITLE": title,
        "NT_MESSAGE": message,
        **env,
    }
    return subprocess.run([BASH, "-c", script], env=environment, capture_output=True, text=True)


def test_it_does_nothing_without_a_webhook(tmp_path):
    result = _notify("", tmp_path, "health", "fail")
    assert result.returncode == 0
    assert not (tmp_path / "personal-cloud-alerts").exists()


def test_first_failure_alerts_then_stays_quiet_then_reports_recovery(hook, tmp_path):
    url = f"http://127.0.0.1:{hook.server_port}/topic"
    assert _notify(url, tmp_path, "health", "ok").returncode == 0  # fine and quiet
    assert _Hook.received == []

    _notify(url, tmp_path, "health", "fail", title="Choud is down", message="unreachable")
    assert len(_Hook.received) == 1
    sent = _Hook.received[0]
    assert sent["body"] == "unreachable"
    assert sent["headers"]["Title"] == "Choud is down"

    _notify(url, tmp_path, "health", "fail")  # still failing: no repeat
    _notify(url, tmp_path, "health", "fail")
    assert len(_Hook.received) == 1

    _notify(url, tmp_path, "health", "ok", title="Choud", message="Healthy again")
    assert len(_Hook.received) == 2
    assert _Hook.received[1]["headers"]["Title"] == "Recovered: Choud"

    _notify(url, tmp_path, "health", "ok")  # fine again: quiet
    assert len(_Hook.received) == 2


def test_a_reminder_is_sent_once_the_interval_has_passed(hook, tmp_path):
    url = f"http://127.0.0.1:{hook.server_port}/t"
    _notify(url, tmp_path, "backup", "fail")
    assert len(_Hook.received) == 1
    state = tmp_path / "personal-cloud-alerts" / "backup.state"
    state.write_bytes(b"fail 1\n")  # the last alert was sent long ago (exact bytes: no CRLF)
    _notify(url, tmp_path, "backup", "fail")
    assert len(_Hook.received) == 2


def test_different_keys_are_tracked_separately(hook, tmp_path):
    url = f"http://127.0.0.1:{hook.server_port}/t"
    _notify(url, tmp_path, "health", "fail")
    _notify(url, tmp_path, "backup", "fail")
    assert len(_Hook.received) == 2


def test_discord_and_slack_get_json_with_escaped_text(hook, tmp_path):
    port = hook.server_port
    _notify(
        f"http://127.0.0.1:{port}/api/webhooks/discord.com/api/webhooks/1",
        tmp_path,
        "d",
        "fail",
        title='Down "now"',
        message="line one\nline two",
    )
    discord = _Hook.received[-1]
    assert discord["headers"]["Content-Type"] == "application/json"
    assert json.loads(discord["body"])["content"] == '**Down "now"**\nline one\nline two'

    _notify(
        f"http://127.0.0.1:{port}/hooks.slack.com/services/x",
        tmp_path,
        "s",
        "fail",
        title="Down",
        message="back\\slash",
    )
    assert json.loads(_Hook.received[-1]["body"])["text"] == "*Down*\nback\\slash"


def test_an_unreachable_webhook_never_fails_the_caller(tmp_path):
    result = _notify("http://127.0.0.1:9/nope", tmp_path, "health", "fail")
    assert result.returncode == 0
    assert "could not reach" in result.stderr
