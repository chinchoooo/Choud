"""Versioning on upload (Phase 6): same-name uploads append versions.

The versions *API* (list/restore/download) has its own tests further down
this file once those endpoints exist; this section covers the upload paths
and the data they leave behind.
"""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.file import File
from app.models.file_version import FileVersion


def _upload(client: TestClient, headers: dict, filename="doc.txt", content=b"v1", **extra):
    data = {k: v for k, v in extra.items() if v is not None}
    return client.post(
        "/api/files/upload",
        files={"file": (filename, content, "text/plain")},
        data=data,
        headers=headers,
    )


def _versions(db: Session, file_id: str) -> list[FileVersion]:
    return list(
        db.execute(
            select(FileVersion)
            .where(FileVersion.file_id == file_id)
            .order_by(FileVersion.version_number)
        ).scalars()
    )


def test_first_upload_creates_version_one_and_points_the_file_at_it(
    client: TestClient, db_session: Session, make_user, auth_headers
) -> None:
    user = make_user()
    body = _upload(client, auth_headers(user)).json()

    versions = _versions(db_session, body["id"])
    assert [v.version_number for v in versions] == [1]
    assert versions[0].content_hash == body["content_hash"]
    assert versions[0].created_by == user.id
    assert versions[0].restored_from_version is None

    file = db_session.get(File, body["id"])
    assert file.current_version_id == versions[0].id


def test_same_name_upload_with_new_content_adds_a_version_not_a_second_file(
    client: TestClient, db_session: Session, make_user, auth_headers, fake_engine_client
) -> None:
    user = make_user()
    headers = auth_headers(user)
    first = _upload(client, headers, content=b"first").json()
    second = _upload(client, headers, content=b"second, longer").json()

    assert second["id"] == first["id"]  # same file, not a duplicate
    assert second["content_hash"] != first["content_hash"]
    assert second["size"] == len(b"second, longer")

    versions = _versions(db_session, first["id"])
    assert [v.version_number for v in versions] == [1, 2]
    assert versions[0].content_hash == first["content_hash"]
    assert versions[1].content_hash == second["content_hash"]
    assert db_session.get(File, first["id"]).current_version_id == versions[1].id

    # Old content must still be physically stored: v1 is recoverable.
    assert fake_engine_client._path_for(first["content_hash"]).is_file()

    listing = client.get("/api/files", headers=headers).json()
    assert len(listing["files"]) == 1


def test_same_name_upload_with_identical_bytes_does_not_add_a_version(
    client: TestClient, db_session: Session, make_user, auth_headers
) -> None:
    user = make_user()
    headers = auth_headers(user)
    first = _upload(client, headers, content=b"unchanged").json()
    second = _upload(client, headers, content=b"unchanged").json()

    assert second["id"] == first["id"]
    assert len(_versions(db_session, first["id"])) == 1


def test_same_name_in_a_different_folder_is_a_separate_file(
    client: TestClient, make_user, auth_headers
) -> None:
    user = make_user()
    headers = auth_headers(user)
    folder = client.post("/api/folders", json={"name": "Docs"}, headers=headers).json()

    root_file = _upload(client, headers, content=b"root").json()
    nested_file = _upload(client, headers, content=b"nested", folder_id=folder["id"]).json()

    assert root_file["id"] != nested_file["id"]


def test_same_name_for_a_different_user_is_a_separate_file(
    client: TestClient, db_session: Session, make_user, auth_headers
) -> None:
    alice = make_user()
    bob = make_user(username="bob", email="bob@example.com")
    alice_file = _upload(client, auth_headers(alice), content=b"alice").json()
    bob_file = _upload(client, auth_headers(bob), content=b"bob").json()

    assert alice_file["id"] != bob_file["id"]
    assert len(_versions(db_session, alice_file["id"])) == 1


def test_uploading_over_a_trashed_file_creates_a_new_file(
    client: TestClient, make_user, auth_headers
) -> None:
    user = make_user()
    headers = auth_headers(user)
    old = _upload(client, headers, content=b"old").json()
    assert client.delete(f"/api/files/{old['id']}", headers=headers).status_code == 204

    new = _upload(client, headers, content=b"new").json()

    assert new["id"] != old["id"]  # the trashed file keeps its own history


def test_rename_onto_an_existing_name_is_rejected(
    client: TestClient, make_user, auth_headers
) -> None:
    user = make_user()
    headers = auth_headers(user)
    _upload(client, headers, filename="a.txt", content=b"a")
    b = _upload(client, headers, filename="b.txt", content=b"b").json()

    response = client.patch(f"/api/files/{b['id']}", json={"name": "a.txt"}, headers=headers)

    assert response.status_code == 409


def test_move_into_a_folder_that_has_the_same_name_is_rejected(
    client: TestClient, make_user, auth_headers
) -> None:
    user = make_user()
    headers = auth_headers(user)
    folder = client.post("/api/folders", json={"name": "Docs"}, headers=headers).json()
    _upload(client, headers, filename="a.txt", content=b"nested", folder_id=folder["id"])
    root_file = _upload(client, headers, filename="a.txt", content=b"root").json()

    response = client.patch(
        f"/api/files/{root_file['id']}", json={"folder_id": folder["id"]}, headers=headers
    )

    assert response.status_code == 409


def test_renaming_a_file_to_its_own_current_name_is_fine(
    client: TestClient, make_user, auth_headers
) -> None:
    user = make_user()
    headers = auth_headers(user)
    f = _upload(client, headers, filename="a.txt", content=b"a").json()

    response = client.patch(f"/api/files/{f['id']}", json={"name": "a.txt"}, headers=headers)

    assert response.status_code == 200


def _chunked_upload(client: TestClient, headers: dict, name: str, content: bytes) -> dict:
    chunk_size = 10
    session = client.post(
        "/api/uploads",
        json={"file_name": name, "file_size": len(content), "chunk_size": chunk_size},
        headers=headers,
    ).json()
    for i in range(0, len(content), chunk_size):
        client.post(
            f"/api/uploads/{session['id']}/chunks/{i // chunk_size}",
            files={"chunk": ("c", content[i : i + chunk_size], "application/octet-stream")},
            headers=headers,
        )
    response = client.post(f"/api/uploads/{session['id']}/complete", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_chunked_upload_over_an_existing_name_adds_a_version(
    client: TestClient, db_session: Session, make_user, auth_headers
) -> None:
    user = make_user()
    headers = auth_headers(user)
    first = _upload(client, headers, filename="big.bin", content=b"small original").json()

    second = _chunked_upload(client, headers, "big.bin", b"X" * 35)

    assert second["id"] == first["id"]
    assert second["size"] == 35
    assert [v.version_number for v in _versions(db_session, first["id"])] == [1, 2]


def test_chunked_upload_of_a_new_name_creates_a_file_with_version_one(
    client: TestClient, db_session: Session, make_user, auth_headers
) -> None:
    user = make_user()
    created = _chunked_upload(client, auth_headers(user), "fresh.bin", b"Y" * 25)

    assert [v.version_number for v in _versions(db_session, created["id"])] == [1]
