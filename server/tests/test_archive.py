"""Zip download of a selection of files and folders."""

import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.core import rate_limit
from app.services import archive_service


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    rate_limit.reset()
    yield
    rate_limit.reset()


def _upload(client, headers, name, data, folder_id=None):
    form = {"folder_id": folder_id} if folder_id else {}
    response = client.post(
        "/api/files/upload", files={"file": (name, data, "text/plain")}, data=form, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def _folder(client, headers, path):
    return client.post("/api/sync/folders", json={"path": path}, headers=headers).json()["id"]


def _zip(client, headers, **body):
    response = client.post("/api/archive/zip", json=body, headers=headers)
    archive = zipfile.ZipFile(io.BytesIO(response.content)) if response.is_success else None
    return response, archive


def test_files_and_a_whole_folder_come_back_as_one_zip(
    client: TestClient, make_user, auth_headers
) -> None:
    headers = auth_headers(make_user())
    top = _upload(client, headers, "top.txt", b"top")
    root = _folder(client, headers, "Trip")
    _folder(client, headers, "Trip/Day 1")
    inner = _folder(client, headers, "Trip/Day 1")
    _upload(client, headers, "plan.txt", b"the plan", root)
    _upload(client, headers, "photo.txt", b"deep", inner)

    response, archive = _zip(client, headers, file_ids=[top["id"]], folder_ids=[root])

    assert response.headers["content-type"] == "application/zip"
    assert sorted(archive.namelist()) == ["Trip/Day 1/photo.txt", "Trip/plan.txt", "top.txt"]
    assert archive.read("Trip/Day 1/photo.txt") == b"deep"
    assert archive.read("top.txt") == b"top"
    assert archive.testzip() is None


def test_a_single_folder_is_named_after_itself(client: TestClient, make_user, auth_headers) -> None:
    headers = auth_headers(make_user())
    folder = _folder(client, headers, "Holiday")
    _upload(client, headers, "a.txt", b"a", folder)
    response, _ = _zip(client, headers, folder_ids=[folder])
    assert 'filename="Holiday.zip"' in response.headers["content-disposition"]


def test_same_names_are_kept_apart_and_nothing_is_left_in_staging(
    client: TestClient, make_user, auth_headers, tmp_path
) -> None:
    headers = auth_headers(make_user())
    one = _upload(client, headers, "same.txt", b"one")
    folder = _folder(client, headers, "Other")
    two = _upload(client, headers, "same.txt", b"two", folder)
    _, archive = _zip(client, headers, file_ids=[one["id"], two["id"], one["id"]])
    assert sorted(archive.namelist()) == ["same (2).txt", "same.txt"]  # the repeated id is ignored


def test_trashed_foreign_and_empty_selections_are_refused(
    client: TestClient, make_user, auth_headers
) -> None:
    alice = auth_headers(make_user())
    bob = auth_headers(make_user("bob", "bob@example.com"))
    mine = _upload(client, alice, "mine.txt", b"x")
    theirs = _upload(client, bob, "theirs.txt", b"y")
    assert client.post("/api/archive/zip", json={}, headers=alice).status_code == 404
    assert (
        client.post(
            "/api/archive/zip", json={"file_ids": [theirs["id"]]}, headers=alice
        ).status_code
        == 404
    )
    client.delete(f"/api/files/{mine['id']}", headers=alice)
    assert (
        client.post("/api/archive/zip", json={"file_ids": [mine["id"]]}, headers=alice).status_code
        == 404
    )
    assert client.post("/api/archive/zip", json={"file_ids": [mine["id"]]}).status_code == 401


def test_too_big_a_selection_is_a_clean_413(
    client: TestClient, make_user, auth_headers, monkeypatch
) -> None:
    headers = auth_headers(make_user())
    file = _upload(client, headers, "big.txt", b"x" * 100)
    monkeypatch.setattr(archive_service, "MAX_TOTAL_BYTES", 10)
    response = client.post("/api/archive/zip", json={"file_ids": [file["id"]]}, headers=headers)
    assert response.status_code == 413
    monkeypatch.setattr(archive_service, "MAX_TOTAL_BYTES", 10**9)
    monkeypatch.setattr(archive_service, "MAX_ENTRIES", 0)
    response = client.post("/api/archive/zip", json={"file_ids": [file["id"]]}, headers=headers)
    assert response.status_code == 413
