"""Trash (Phase 6): list, restore, permanently delete, and object cleanup."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.file import File
from app.models.file_version import FileVersion
from app.services.engine_client import EngineUnavailableError
from app.services.trash_service import MAX_NAME_LENGTH, _restored_name


def _upload(client: TestClient, headers: dict, filename="doc.txt", content=b"v1", **extra):
    data = {k: v for k, v in extra.items() if v is not None}
    response = client.post(
        "/api/files/upload",
        files={"file": (filename, content, "text/plain")},
        data=data,
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _trash(client: TestClient, headers: dict, file_id: str) -> None:
    assert client.delete(f"/api/files/{file_id}", headers=headers).status_code == 204


def _listing_ids(client: TestClient, headers: dict, **params) -> list[str]:
    response = client.get("/api/files", params=params, headers=headers)
    return [f["id"] for f in response.json()["files"]]


def _trash_ids(client: TestClient, headers: dict) -> list[str]:
    return [f["id"] for f in client.get("/api/trash", headers=headers).json()["files"]]


# --- list + restore --------------------------------------------------------


def test_deleted_file_shows_in_trash_not_in_listing_and_restores(
    client: TestClient, make_user, auth_headers
) -> None:
    headers = auth_headers(make_user())
    f = _upload(client, headers, content=b"precious")

    _trash(client, headers, f["id"])
    assert _trash_ids(client, headers) == [f["id"]]
    assert _listing_ids(client, headers) == []

    restored = client.post(f"/api/trash/{f['id']}/restore", headers=headers)

    assert restored.status_code == 200
    assert restored.json()["id"] == f["id"]
    assert restored.json()["name"] == "doc.txt"
    assert _listing_ids(client, headers) == [f["id"]]
    assert _trash_ids(client, headers) == []
    download = client.get(f"/api/files/{f['id']}/download", headers=headers)
    assert download.content == b"precious"


def test_trash_listing_has_metadata_and_is_most_recent_first(
    client: TestClient, make_user, auth_headers
) -> None:
    headers = auth_headers(make_user())
    first = _upload(client, headers, filename="first.txt", content=b"1")
    second = _upload(client, headers, filename="second.txt", content=b"22")
    _trash(client, headers, first["id"])
    _trash(client, headers, second["id"])

    files = client.get("/api/trash", headers=headers).json()["files"]

    assert [f["name"] for f in files] == ["second.txt", "first.txt"]
    assert files[0]["size"] == 2
    assert files[0]["deleted_at"]


def test_trash_only_contains_the_callers_files(
    client: TestClient, make_user, auth_headers
) -> None:
    alice = make_user()
    bob = make_user(username="bob", email="bob@example.com")
    a = _upload(client, auth_headers(alice), content=b"alice")
    _trash(client, auth_headers(alice), a["id"])

    assert _trash_ids(client, auth_headers(bob)) == []
    restore = client.post(f"/api/trash/{a['id']}/restore", headers=auth_headers(bob))
    assert restore.status_code == 404
    purge = client.delete(f"/api/trash/{a['id']}", headers=auth_headers(bob))
    assert purge.status_code == 404
    assert _trash_ids(client, auth_headers(alice)) == [a["id"]]  # untouched


def test_restoring_or_purging_a_live_or_unknown_file_is_404(
    client: TestClient, make_user, auth_headers
) -> None:
    headers = auth_headers(make_user())
    live = _upload(client, headers)
    missing = "00000000-0000-0000-0000-000000000000"

    for file_id in (live["id"], missing):
        assert client.post(f"/api/trash/{file_id}/restore", headers=headers).status_code == 404
        assert client.delete(f"/api/trash/{file_id}", headers=headers).status_code == 404
    assert _listing_ids(client, headers) == [live["id"]]  # the live file survived


def test_trash_endpoints_require_authentication(client: TestClient) -> None:
    fid = "00000000-0000-0000-0000-000000000000"
    assert client.get("/api/trash").status_code == 401
    assert client.post(f"/api/trash/{fid}/restore").status_code == 401
    assert client.delete(f"/api/trash/{fid}").status_code == 401


def test_restore_keeps_the_original_folder(client: TestClient, make_user, auth_headers) -> None:
    headers = auth_headers(make_user())
    folder = client.post("/api/folders", json={"name": "Docs"}, headers=headers).json()
    f = _upload(client, headers, folder_id=folder["id"])
    _trash(client, headers, f["id"])

    restored = client.post(f"/api/trash/{f['id']}/restore", headers=headers).json()

    assert restored["folder_id"] == folder["id"]


def test_restore_goes_to_the_root_when_the_original_folder_was_deleted(
    client: TestClient, make_user, auth_headers
) -> None:
    headers = auth_headers(make_user())
    folder = client.post("/api/folders", json={"name": "Gone"}, headers=headers).json()
    f = _upload(client, headers, folder_id=folder["id"])
    _trash(client, headers, f["id"])
    assert client.delete(f"/api/folders/{folder['id']}", headers=headers).status_code == 204

    restored = client.post(f"/api/trash/{f['id']}/restore", headers=headers)

    assert restored.status_code == 200
    assert restored.json()["folder_id"] is None
    assert _listing_ids(client, headers) == [f["id"]]


def test_restore_over_a_taken_name_adds_a_suffix_and_keeps_the_extension(
    client: TestClient, make_user, auth_headers
) -> None:
    headers = auth_headers(make_user())
    old = _upload(client, headers, filename="report.pdf", content=b"old report")
    _trash(client, headers, old["id"])
    current = _upload(client, headers, filename="report.pdf", content=b"new report")
    assert current["id"] != old["id"]

    restored = client.post(f"/api/trash/{old['id']}/restore", headers=headers).json()

    assert restored["name"] == "report (restored).pdf"
    # Neither file was overwritten.
    old_download = client.get(f"/api/files/{old['id']}/download", headers=headers)
    assert old_download.content == b"old report"
    new_download = client.get(f"/api/files/{current['id']}/download", headers=headers)
    assert new_download.content == b"new report"


def test_repeated_name_clashes_get_increasing_suffixes(
    client: TestClient, make_user, auth_headers
) -> None:
    headers = auth_headers(make_user())
    trashed_ids = []
    for i in range(3):
        f = _upload(client, headers, filename="a.txt", content=f"copy {i}".encode())
        _trash(client, headers, f["id"])  # frees the name for the next round
        trashed_ids.append(f["id"])
    live = _upload(client, headers, filename="a.txt", content=b"live")
    assert live["name"] == "a.txt"

    restored_names = [
        client.post(f"/api/trash/{fid}/restore", headers=headers).json()["name"]
        for fid in trashed_ids
    ]

    assert restored_names == ["a (restored).txt", "a (restored 2).txt", "a (restored 3).txt"]


def test_restored_name_stays_within_the_length_limit() -> None:
    long_name = "x" * 251 + ".txt"  # exactly 255 characters
    assert len(long_name) == MAX_NAME_LENGTH

    result = _restored_name(long_name, 1)

    assert len(result) <= MAX_NAME_LENGTH
    assert result.endswith(" (restored).txt")


def test_restoring_a_file_keeps_its_version_history(
    client: TestClient, make_user, auth_headers
) -> None:
    headers = auth_headers(make_user())
    f = _upload(client, headers, content=b"one")
    _upload(client, headers, content=b"two")
    _trash(client, headers, f["id"])

    client.post(f"/api/trash/{f['id']}/restore", headers=headers)

    versions = client.get(f"/api/files/{f['id']}/versions", headers=headers).json()["versions"]
    assert [v["version_number"] for v in versions] == [2, 1]


# --- purge -----------------------------------------------------------------


def _rows(db: Session, file_id: str) -> tuple[File | None, list[FileVersion]]:
    return (
        db.get(File, file_id),
        list(db.execute(select(FileVersion).where(FileVersion.file_id == file_id)).scalars()),
    )


def test_purge_removes_the_file_its_versions_and_unreferenced_objects(
    client: TestClient, db_session: Session, make_user, auth_headers, fake_engine_client
) -> None:
    headers = auth_headers(make_user())
    v1 = _upload(client, headers, content=b"first version")
    v2 = _upload(client, headers, content=b"second version")
    _trash(client, headers, v1["id"])
    assert fake_engine_client._path_for(v1["content_hash"]).is_file()
    assert fake_engine_client._path_for(v2["content_hash"]).is_file()

    response = client.delete(f"/api/trash/{v1['id']}", headers=headers)

    assert response.status_code == 204
    file, versions = _rows(db_session, v1["id"])
    assert file is None
    assert versions == []
    assert not fake_engine_client._path_for(v1["content_hash"]).exists()
    assert not fake_engine_client._path_for(v2["content_hash"]).exists()
    assert _trash_ids(client, headers) == []
    assert client.post(f"/api/trash/{v1['id']}/restore", headers=headers).status_code == 404


def test_purge_keeps_an_object_still_used_by_another_live_file(
    client: TestClient, make_user, auth_headers, fake_engine_client
) -> None:
    headers = auth_headers(make_user())
    doomed = _upload(client, headers, filename="a.txt", content=b"shared bytes")
    survivor = _upload(client, headers, filename="b.txt", content=b"shared bytes")
    assert doomed["content_hash"] == survivor["content_hash"]
    _trash(client, headers, doomed["id"])

    assert client.delete(f"/api/trash/{doomed['id']}", headers=headers).status_code == 204

    assert fake_engine_client._path_for(survivor["content_hash"]).is_file()
    download = client.get(f"/api/files/{survivor['id']}/download", headers=headers)
    assert download.content == b"shared bytes"


def test_purge_keeps_an_object_still_used_by_another_users_file(
    client: TestClient, make_user, auth_headers, fake_engine_client
) -> None:
    alice = make_user()
    bob = make_user(username="bob", email="bob@example.com")
    a = _upload(client, auth_headers(alice), content=b"identical across users")
    b = _upload(client, auth_headers(bob), content=b"identical across users")
    _trash(client, auth_headers(alice), a["id"])

    purge = client.delete(f"/api/trash/{a['id']}", headers=auth_headers(alice))
    assert purge.status_code == 204

    assert fake_engine_client._path_for(a["content_hash"]).is_file()
    download = client.get(f"/api/files/{b['id']}/download", headers=auth_headers(bob))
    assert download.content == b"identical across users"


def test_purge_keeps_an_object_that_is_only_an_old_version_of_another_file(
    client: TestClient, make_user, auth_headers, fake_engine_client
) -> None:
    headers = auth_headers(make_user())
    other = _upload(client, headers, filename="other.txt", content=b"history bytes")
    _upload(client, headers, filename="other.txt", content=b"newer bytes")  # v1 is now old
    doomed = _upload(client, headers, filename="doomed.txt", content=b"history bytes")
    _trash(client, headers, doomed["id"])

    client.delete(f"/api/trash/{doomed['id']}", headers=headers)

    # other.txt's version 1 still needs those bytes.
    assert fake_engine_client._path_for(other["content_hash"]).is_file()
    versions = client.get(f"/api/files/{other['id']}/versions", headers=headers).json()["versions"]
    old = next(v for v in versions if v["version_number"] == 1)
    kept = client.get(f"/api/files/{other['id']}/versions/{old['id']}/download", headers=headers)
    assert kept.content == b"history bytes"


def test_purge_succeeds_even_if_the_engine_cannot_delete_the_object(
    client: TestClient,
    db_session: Session,
    make_user,
    auth_headers,
    fake_engine_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = auth_headers(make_user())
    f = _upload(client, headers, content=b"orphan me")
    _trash(client, headers, f["id"])

    def _boom(content_hash: str) -> bool:
        raise EngineUnavailableError("engine is down")

    monkeypatch.setattr(fake_engine_client, "delete", _boom)

    response = client.delete(f"/api/trash/{f['id']}", headers=headers)

    # The metadata is gone; the bytes are left behind as an unreferenced
    # orphan for garbage collection rather than failing or guessing.
    assert response.status_code == 204
    assert _rows(db_session, f["id"]) == (None, [])
    assert fake_engine_client._path_for(f["content_hash"]).is_file()


def test_purge_does_not_touch_other_files_in_the_trash(
    client: TestClient, make_user, auth_headers
) -> None:
    headers = auth_headers(make_user())
    a = _upload(client, headers, filename="a.txt", content=b"a")
    b = _upload(client, headers, filename="b.txt", content=b"b")
    _trash(client, headers, a["id"])
    _trash(client, headers, b["id"])

    client.delete(f"/api/trash/{a['id']}", headers=headers)

    assert _trash_ids(client, headers) == [b["id"]]
