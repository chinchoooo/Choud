"""Space insights, version pruning, memories, the sign-in history and the admin server view."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.models.file import File
from app.models.login_event import LoginEvent


def _upload(client, headers, name, data, mime="text/plain", folder_id=None):
    form = {"folder_id": folder_id} if folder_id else {}
    response = client.post(
        "/api/files/upload", files={"file": (name, data, mime)}, data=form, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


# --- space insights -------------------------------------------------------------------------


def test_space_report_shows_dedup_history_and_duplicates(
    client: TestClient, make_user, auth_headers
) -> None:
    headers = auth_headers(make_user())
    _upload(client, headers, "a.txt", b"same bytes here")
    _upload(client, headers, "b.txt", b"same bytes here")  # identical content, other name
    _upload(client, headers, "doc.txt", b"version one")
    _upload(client, headers, "doc.txt", b"version two is longer")
    _upload(client, headers, "pic.jpg", b"\xff\xd8" + b"p" * 50, "image/jpeg")

    report = client.get("/api/insights/space", headers=headers).json()

    same = len(b"same bytes here")
    assert report["dedup_saved_bytes"] == same  # a.txt and b.txt are stored once
    assert report["logical_bytes"] - report["stored_bytes"] == same
    assert report["history_bytes"] == len(b"version one")  # held only by the old version
    assert report["current_bytes"] == 2 * same + len(b"version two is longer") + 52
    assert report["by_type"]["Photos"] == 52
    assert report["biggest"][0]["size"] >= report["biggest"][-1]["size"]
    assert report["duplicate_files"] == 1
    group = report["duplicates"][0]
    assert group["copies"] == 2 and {f["name"] for f in group["files"]} == {"a.txt", "b.txt"}
    assert report["quota_bytes"] > 0


def test_pruning_previews_first_then_keeps_the_current_version(
    client: TestClient, make_user, auth_headers
) -> None:
    headers = auth_headers(make_user())
    file = _upload(client, headers, "doc.txt", b"v1")
    for number in range(2, 6):
        _upload(client, headers, "doc.txt", f"v{number}".encode())

    preview = client.post("/api/insights/prune-versions", json={"keep": 2}, headers=headers).json()
    assert preview["dry_run"] is True and preview["versions_removed"] == 3
    assert (
        len(client.get(f"/api/files/{file['id']}/versions", headers=headers).json()["versions"])
        == 5
    )

    done = client.post(
        "/api/insights/prune-versions", json={"keep": 2, "dry_run": False}, headers=headers
    ).json()
    assert done["versions_removed"] == 3 and done["files_affected"] == 1
    versions = client.get(f"/api/files/{file['id']}/versions", headers=headers).json()["versions"]
    assert [v["version_number"] for v in versions] == [5, 4]
    content = client.get(f"/api/files/{file['id']}/download", headers=headers).content
    assert content == b"v5"  # the current version always survives
    assert (
        client.post("/api/insights/prune-versions", json={"keep": 0}, headers=headers).status_code
        == 422
    )


def test_pruning_never_removes_an_object_another_file_still_uses(
    client: TestClient, make_user, auth_headers
) -> None:
    headers = auth_headers(make_user())
    shared = _upload(client, headers, "shared.txt", b"precious shared bytes")
    other = _upload(client, headers, "other.txt", b"precious shared bytes")
    for n in range(3):
        _upload(client, headers, "shared.txt", f"newer {n}".encode())
    client.post("/api/insights/prune-versions", json={"keep": 1, "dry_run": False}, headers=headers)
    # other.txt still points at the original bytes, so they must still be downloadable.
    content = client.get(f"/api/files/{other['id']}/download", headers=headers).content
    assert content == b"precious shared bytes"
    assert shared["id"] != other["id"]


def test_insights_are_private_to_the_account(client: TestClient, make_user, auth_headers) -> None:
    alice = auth_headers(make_user())
    bob = auth_headers(make_user("bob", "bob@example.com"))
    _upload(client, alice, "big.bin", b"x" * 500, "application/octet-stream")
    mine = client.get("/api/insights/space", headers=bob).json()
    assert mine["logical_bytes"] == 0 and mine["biggest"] == []
    assert client.get("/api/insights/space").status_code == 401


# --- on this day ----------------------------------------------------------------------------


def test_memories_are_photos_from_this_day_in_earlier_years(
    client: TestClient, make_user, auth_headers, db_session
) -> None:
    headers = auth_headers(make_user())
    today = datetime.now()
    old = _upload(client, headers, "then.jpg", b"1", "image/jpeg")
    new = _upload(client, headers, "now.jpg", b"2", "image/jpeg")
    other_day = _upload(client, headers, "other.jpg", b"3", "image/jpeg")
    note = _upload(client, headers, "note.txt", b"4")  # not a photo
    for item, when in (
        (old, datetime(today.year - 3, today.month, today.day, 9, 30, tzinfo=UTC)),
        (new, datetime(today.year, today.month, today.day, 9, 30, tzinfo=UTC)),
        (other_day, datetime(today.year - 1, 1 if today.month != 1 else 2, 15, tzinfo=UTC)),
        (note, datetime(today.year - 2, today.month, today.day, 9, 30, tzinfo=UTC)),
    ):
        row = db_session.get(File, item["id"])
        row.taken_at = when
    db_session.commit()

    groups = client.get("/api/library/memories", headers=headers).json()
    assert [(g["year"], g["years_ago"]) for g in groups] == [(today.year - 3, 3)]
    assert [f["name"] for f in groups[0]["files"]] == ["then.jpg"]


# --- sign-in history ------------------------------------------------------------------------


def _login(client, password="password123", ip="203.0.113.5", agent="TestBrowser/1", **extra):
    return client.post(
        "/api/auth/login",
        json={"email": "alice@example.com", "password": password, **extra},
        headers={"X-Forwarded-For": ip, "User-Agent": agent},
    )


def test_the_security_log_records_successes_failures_and_new_devices(
    client: TestClient, make_user, auth_headers, db_session
) -> None:
    user = make_user()
    headers = auth_headers(user)

    assert _login(client).status_code == 200  # first ever: not "new"
    assert _login(client, password="wrong-password").status_code == 401
    assert _login(client, ip="198.51.100.9", agent="Phone/2").status_code == 200  # a new device
    assert _login(client, ip="198.51.100.9", agent="Phone/2").status_code == 200  # now familiar

    log = client.get("/api/auth/security-log", headers=headers).json()
    assert [(e["success"], e["new_device"]) for e in log] == [
        (True, False),
        (True, True),
        (False, False),
        (True, False),
    ]
    assert log[0]["ip"] == "198.51.100.9" and log[0]["user_agent"] == "Phone/2"
    assert client.get("/api/auth/security-log").status_code == 401


def test_unknown_emails_leave_no_trace_and_logs_are_private(
    client: TestClient, make_user, auth_headers, db_session
) -> None:
    make_user()
    bob = auth_headers(make_user("bob", "bob@example.com"))
    client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "x" * 10})
    assert db_session.query(LoginEvent).count() == 0
    _login(client)
    assert client.get("/api/auth/security-log", headers=bob).json() == []


def test_a_wrong_two_factor_code_is_recorded(
    client: TestClient, make_user, auth_headers, db_session
) -> None:
    from app.core import totp

    user = make_user()
    headers = auth_headers(user)
    secret = client.post("/api/auth/2fa/setup", headers=headers).json()["secret"]
    client.post(
        "/api/auth/2fa/enable",
        json={"code": totp.code_at(secret, totp.current_step())},
        headers=headers,
    )
    _login(client, otp="000000")
    log = client.get("/api/auth/security-log", headers=headers).json()
    assert log and log[0]["success"] is False


# --- admin ----------------------------------------------------------------------------------


def test_only_the_administrator_sees_the_server_view(
    client: TestClient, make_user, auth_headers
) -> None:
    admin = auth_headers(make_user("admin", "admin@example.com"))
    other = auth_headers(make_user("other", "other@example.com"))
    _upload(client, admin, "a.txt", b"hello world")

    status = client.get("/api/admin/server", headers=admin)
    assert status.status_code == 200
    body = status.json()
    assert body["users"] == 2 and body["files"] == 1 and body["versions"] == 1
    assert body["logical_bytes"] == body["stored_bytes"] == len(b"hello world")
    assert body["disk_total_bytes"] >= body["disk_free_bytes"] >= 0
    assert body["registration_mode"] in {"invite", "open", "closed"}
    assert client.get("/api/admin/server", headers=other).status_code == 403
    assert client.get("/api/admin/server").status_code == 401
