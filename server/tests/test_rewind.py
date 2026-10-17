"""Rewind: browse and restore files as they were at an earlier time."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models.file import File
from app.models.file_version import FileVersion
from app.models.folder import Folder

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
BEFORE = T0 + timedelta(days=1)  # the moment we will rewind to
AFTER = T0 + timedelta(days=2)


def _upload(client, headers, name, data, folder_id=None):
    form = {"folder_id": folder_id} if folder_id else {}
    response = client.post(
        "/api/files/upload", files={"file": (name, data, "text/plain")}, data=form, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def _folder(client, headers, path):
    return client.post("/api/sync/folders", json={"path": path}, headers=headers).json()["id"]


def _stamp(db, file_id, when):
    """Pretend every version of this file so far was made at `when`."""
    for version in db.execute(select(FileVersion).where(FileVersion.file_id == file_id)).scalars():
        version.created_at = when
    db.commit()


def _stamp_new(db, file_id, when):
    """Pretend only the newest version was made at `when`."""
    versions = list(
        db.execute(
            select(FileVersion)
            .where(FileVersion.file_id == file_id)
            .order_by(FileVersion.version_number)
        ).scalars()
    )
    versions[-1].created_at = when
    db.commit()


def _text(client, headers, file_id):
    return client.get(f"/api/files/{file_id}/download", headers=headers).content


def _scenario(client, headers, db):
    """a.txt edited, b.txt deleted, c.txt created: all after the moment we rewind to."""
    folder = _folder(client, headers, "Work")
    a = _upload(client, headers, "a.txt", b"a original", folder)
    b = _upload(client, headers, "b.txt", b"b original", folder)
    for item in (a, b):
        _stamp(db, item["id"], T0)
    for row in db.execute(select(Folder)).scalars():
        row.created_at = T0
    db.commit()

    _upload(client, headers, "a.txt", b"a ENCRYPTED BY MALWARE", folder)
    _stamp_new(db, a["id"], AFTER)
    client.delete(f"/api/files/{b['id']}", headers=headers)
    row = db.get(File, b["id"])
    row.deleted_at = AFTER
    db.commit()
    c = _upload(client, headers, "ransom-note.txt", b"pay up", folder)
    _stamp(db, c["id"], AFTER)
    return folder, a, b, c


def _at(moment):
    return moment.isoformat()


def test_browse_shows_the_folder_as_it_was(
    client: TestClient, make_user, auth_headers, db_session
) -> None:
    headers = auth_headers(make_user())
    folder, a, b, c = _scenario(client, headers, db_session)

    result = client.get(
        "/api/rewind/browse", params={"at": _at(BEFORE), "folder_id": folder}, headers=headers
    ).json()

    by_name = {f["name"]: f for f in result["files"]}
    assert set(by_name) == {"a.txt", "b.txt"}  # the ransom note did not exist yet
    assert by_name["a.txt"]["changed"] is True and by_name["a.txt"]["version_number"] == 1
    assert by_name["b.txt"]["trashed"] is True  # in the trash today, but it existed then
    assert result["folder_name"] == "Work"

    now = client.get(
        "/api/rewind/browse",
        params={"at": _at(AFTER + timedelta(hours=1)), "folder_id": folder},
        headers=headers,
    ).json()
    # After the deletion b.txt no longer existed; the ransom note did.
    assert {f["name"] for f in now["files"]} == {"a.txt", "ransom-note.txt"}


def test_preview_changes_nothing_then_restore_puts_everything_back(
    client: TestClient, make_user, auth_headers, db_session
) -> None:
    headers = auth_headers(make_user())
    folder, a, b, c = _scenario(client, headers, db_session)

    preview = client.post(
        "/api/rewind/restore-tree", json={"folder_id": folder, "at": _at(BEFORE)}, headers=headers
    ).json()
    assert preview["dry_run"] is True
    assert preview["restored_content"] == 1 and preview["undeleted"] == 1
    assert preview["newer_untouched"] == 1
    assert _text(client, headers, a["id"]) == b"a ENCRYPTED BY MALWARE"  # still untouched

    done = client.post(
        "/api/rewind/restore-tree",
        json={"folder_id": folder, "at": _at(BEFORE), "dry_run": False},
        headers=headers,
    ).json()
    assert done["restored_content"] == 1 and done["undeleted"] == 1

    assert _text(client, headers, a["id"]) == b"a original"
    assert _text(client, headers, b["id"]) == b"b original"
    assert client.get("/api/trash", headers=headers).json()["files"] == []
    listing = client.get(f"/api/files?folder_id={folder}", headers=headers).json()
    assert {f["name"] for f in listing["files"]} == {"a.txt", "b.txt", "ransom-note.txt"}

    # Nothing was destroyed: the malware's version is still in the history, as a newer version.
    versions = client.get(f"/api/files/{a['id']}/versions", headers=headers).json()["versions"]
    assert len(versions) == 3


def test_restoring_twice_is_safe(client: TestClient, make_user, auth_headers, db_session) -> None:
    headers = auth_headers(make_user())
    folder, a, *_ = _scenario(client, headers, db_session)
    body = {"folder_id": folder, "at": _at(BEFORE), "dry_run": False}
    client.post("/api/rewind/restore-tree", json=body, headers=headers)
    again = client.post("/api/rewind/restore-tree", json=body, headers=headers).json()
    assert again["restored_content"] == 0 and again["undeleted"] == 0
    assert (
        len(client.get(f"/api/files/{a['id']}/versions", headers=headers).json()["versions"]) == 3
    )


def test_restore_one_file(client: TestClient, make_user, auth_headers, db_session) -> None:
    headers = auth_headers(make_user())
    folder, a, b, c = _scenario(client, headers, db_session)
    ok = client.post(
        "/api/rewind/restore-file", json={"file_id": a["id"], "at": _at(BEFORE)}, headers=headers
    )
    assert ok.status_code == 200 and ok.json()["restored_content"] == 1
    assert _text(client, headers, a["id"]) == b"a original"
    missing = client.post(
        "/api/rewind/restore-file", json={"file_id": c["id"], "at": _at(BEFORE)}, headers=headers
    )
    assert missing.status_code == 404  # it did not exist then


def test_whole_account_rewind_and_safety_checks(
    client: TestClient, make_user, auth_headers, db_session
) -> None:
    alice = auth_headers(make_user())
    bob = auth_headers(make_user("bob", "bob@example.com"))
    folder, a, b, c = _scenario(client, alice, db_session)

    # Rewinding the whole account (no folder) finds the same files.
    preview = client.post(
        "/api/rewind/restore-tree", json={"at": _at(BEFORE)}, headers=alice
    ).json()
    assert preview["restored_content"] == 1 and preview["undeleted"] == 1

    # Other people's data is out of reach, and the future cannot be browsed.
    assert (
        client.post(
            "/api/rewind/restore-file", json={"file_id": a["id"], "at": _at(BEFORE)}, headers=bob
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/api/rewind/browse", params={"at": _at(BEFORE), "folder_id": folder}, headers=bob
        ).status_code
        == 404
    )
    future = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    assert client.get("/api/rewind/browse", params={"at": future}, headers=alice).status_code == 422
    assert client.get("/api/rewind/browse", params={"at": _at(BEFORE)}).status_code == 401
