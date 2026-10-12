"""Sync client endpoints: the flat snapshot and idempotent folder paths."""

import pytest
from fastapi.testclient import TestClient


def _upload(client: TestClient, headers: dict, name="a.txt", content=b"x", folder_id=None):
    data = {"folder_id": folder_id} if folder_id else {}
    response = client.post(
        "/api/files/upload", files={"file": (name, content)}, data=data, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def _snapshot(client: TestClient, headers: dict) -> dict:
    response = client.get("/api/sync/snapshot", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_empty_account_has_an_empty_snapshot(client: TestClient, make_user, auth_headers) -> None:
    body = _snapshot(client, auth_headers(make_user()))

    assert body["folders"] == [] and body["files"] == []
    assert body["generated_at"]


def test_snapshot_lists_every_file_and_folder_with_full_paths(
    client: TestClient, make_user, auth_headers
) -> None:
    headers = auth_headers(make_user())
    research = client.post("/api/folders", json={"name": "Research"}, headers=headers).json()
    year = client.post(
        "/api/folders", json={"name": "2026", "parent_id": research["id"]}, headers=headers
    ).json()
    _upload(client, headers, name="root.txt", content=b"r")
    _upload(client, headers, name="paper.pdf", content=b"p", folder_id=year["id"])

    body = _snapshot(client, headers)

    assert [f["path"] for f in body["folders"]] == ["Research", "Research/2026"]
    assert [f["path"] for f in body["files"]] == ["Research/2026/paper.pdf", "root.txt"]
    paper = next(f for f in body["files"] if f["name"] == "paper.pdf")
    assert paper["folder_id"] == year["id"]
    assert paper["size"] == 1
    assert len(paper["content_hash"]) == 64
    assert paper["version_id"]  # what a client sends back as base_version_id


def test_snapshot_version_id_moves_when_a_file_is_edited(
    client: TestClient, make_user, auth_headers
) -> None:
    headers = auth_headers(make_user())
    _upload(client, headers, content=b"one")
    before = _snapshot(client, headers)["files"][0]

    _upload(client, headers, content=b"two")
    after = _snapshot(client, headers)["files"][0]

    assert after["id"] == before["id"]
    assert after["version_id"] != before["version_id"]
    assert after["content_hash"] != before["content_hash"]


def test_trashed_files_are_absent_from_the_snapshot(
    client: TestClient, make_user, auth_headers
) -> None:
    headers = auth_headers(make_user())
    gone = _upload(client, headers, name="gone.txt")
    _upload(client, headers, name="kept.txt")
    client.delete(f"/api/files/{gone['id']}", headers=headers)

    assert [f["path"] for f in _snapshot(client, headers)["files"]] == ["kept.txt"]


def test_snapshot_only_contains_the_callers_data(
    client: TestClient, make_user, auth_headers
) -> None:
    alice = make_user()
    bob = make_user(username="bob", email="bob@example.com")
    _upload(client, auth_headers(alice), name="alice.txt")
    client.post("/api/folders", json={"name": "AliceOnly"}, headers=auth_headers(alice))

    body = _snapshot(client, auth_headers(bob))

    assert body["files"] == [] and body["folders"] == []


def test_snapshot_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/sync/snapshot").status_code == 401
    assert client.post("/api/sync/folders", json={"path": "a"}).status_code == 401


# --- ensure folder path -------------------------------------------------------


def test_ensure_creates_the_whole_path_and_returns_the_leaf(
    client: TestClient, make_user, auth_headers
) -> None:
    headers = auth_headers(make_user())

    response = client.post("/api/sync/folders", json={"path": "a/b/c"}, headers=headers)

    assert response.status_code == 200
    assert response.json()["path"] == "a/b/c"
    assert [f["path"] for f in _snapshot(client, headers)["folders"]] == ["a", "a/b", "a/b/c"]
    leaf = next(f for f in _snapshot(client, headers)["folders"] if f["path"] == "a/b/c")
    assert response.json()["id"] == leaf["id"]


def test_ensure_is_idempotent_and_reuses_existing_folders(
    client: TestClient, make_user, auth_headers
) -> None:
    headers = auth_headers(make_user())
    existing = client.post("/api/folders", json={"name": "Docs"}, headers=headers).json()

    first = client.post("/api/sync/folders", json={"path": "Docs/Sub"}, headers=headers).json()
    second = client.post("/api/sync/folders", json={"path": "Docs/Sub"}, headers=headers).json()

    assert first == second
    paths = [f["path"] for f in _snapshot(client, headers)["folders"]]
    assert paths == ["Docs", "Docs/Sub"]  # no duplicates
    docs = next(f for f in _snapshot(client, headers)["folders"] if f["path"] == "Docs")
    assert docs["id"] == existing["id"]  # the pre-existing folder was reused


@pytest.mark.parametrize("path", ["", "/", "//"])
def test_ensure_with_an_empty_path_is_the_root(
    client: TestClient, make_user, auth_headers, path: str
) -> None:
    response = client.post(
        "/api/sync/folders", json={"path": path}, headers=auth_headers(make_user())
    )

    assert response.status_code == 200
    assert response.json() == {"id": None, "path": ""}


def test_ensure_ignores_leading_and_trailing_slashes(
    client: TestClient, make_user, auth_headers
) -> None:
    response = client.post(
        "/api/sync/folders", json={"path": "/x/y/"}, headers=auth_headers(make_user())
    )

    assert response.json()["path"] == "x/y"


@pytest.mark.parametrize("path", ["../escape", "a/../b", "a/./b", "a\\b", "a/\x00/b", "x" * 256])
def test_ensure_rejects_traversal_and_illegal_names(
    client: TestClient, make_user, auth_headers, path: str
) -> None:
    headers = auth_headers(make_user())

    response = client.post("/api/sync/folders", json={"path": path}, headers=headers)

    assert response.status_code == 422
    assert _snapshot(client, headers)["folders"] == []  # nothing was created


def test_ensure_rejects_an_absurdly_deep_path(client: TestClient, make_user, auth_headers) -> None:
    response = client.post(
        "/api/sync/folders", json={"path": "/".join(["d"] * 65)}, headers=auth_headers(make_user())
    )

    assert response.status_code == 422


def test_ensure_never_touches_another_users_folders(
    client: TestClient, make_user, auth_headers
) -> None:
    alice = make_user()
    bob = make_user(username="bob", email="bob@example.com")
    alices = client.post(
        "/api/sync/folders", json={"path": "Shared"}, headers=auth_headers(alice)
    ).json()

    bobs = client.post(
        "/api/sync/folders", json={"path": "Shared"}, headers=auth_headers(bob)
    ).json()

    assert alices["id"] != bobs["id"]


# --- ETag / conditional snapshot -------------------------------------------------------


def _etag(client: TestClient, headers: dict) -> str:
    response = client.get("/api/sync/snapshot", headers=headers)
    assert response.status_code == 200
    return response.headers["ETag"]


def test_snapshot_has_a_stable_etag_and_answers_304_when_nothing_changed(
    client: TestClient, make_user, auth_headers
) -> None:
    headers = auth_headers(make_user())
    _upload(client, headers, name="a.txt")
    etag = _etag(client, headers)
    assert etag.startswith('"') and etag.endswith('"')
    assert _etag(client, headers) == etag  # deterministic

    again = client.get("/api/sync/snapshot", headers={**headers, "If-None-Match": etag})

    assert again.status_code == 304
    assert again.content == b""  # no body: that is the whole point
    assert again.headers["ETag"] == etag


def test_a_stale_etag_gets_the_full_snapshot(client: TestClient, make_user, auth_headers) -> None:
    headers = auth_headers(make_user())
    stale = _etag(client, headers)
    _upload(client, headers, name="new.txt")

    response = client.get("/api/sync/snapshot", headers={**headers, "If-None-Match": stale})

    assert response.status_code == 200
    assert response.headers["ETag"] != stale
    assert [f["path"] for f in response.json()["files"]] == ["new.txt"]


def test_every_kind_of_change_alters_the_etag(client: TestClient, make_user, auth_headers) -> None:
    headers = auth_headers(make_user())
    history = [_etag(client, headers)]

    def changed(label: str) -> None:
        # Each change must differ from the state right before it.
        history.append(_etag(client, headers))
        assert history[-1] != history[-2], f"{label} did not change the ETag"

    first = _upload(client, headers, name="a.txt", content=b"one")
    changed("a new file")
    _upload(client, headers, name="a.txt", content=b"two")
    changed("a new version")
    client.patch(f"/api/files/{first['id']}", json={"name": "b.txt"}, headers=headers)
    changed("a rename")
    folder = client.post("/api/folders", json={"name": "F"}, headers=headers).json()
    changed("a new folder")
    client.patch(f"/api/files/{first['id']}", json={"folder_id": folder["id"]}, headers=headers)
    changed("a move")
    before_trash = history[-1]
    client.delete(f"/api/files/{first['id']}", headers=headers)
    changed("moving a file to the trash")
    client.post(f"/api/trash/{first['id']}/restore", headers=headers)
    changed("restoring from the trash")
    # Restoring puts the tree back exactly as it was, so the fingerprint - which is
    # derived from content, not from a counter - returns to its earlier value too.
    assert history[-1] == before_trash
    client.delete(f"/api/folders/{folder['id']}", headers=headers)  # non-empty: 409, no change
    assert _etag(client, headers) == history[-1]


def test_etag_is_per_user(client: TestClient, make_user, auth_headers) -> None:
    alice = make_user()
    bob = make_user(username="bob", email="bob@example.com")
    _upload(client, auth_headers(alice), name="alice.txt")

    # Bob's empty tree is unaffected by Alice's uploads, and Alice's ETag does
    # not match Bob's tree, so it cannot be used to learn anything about it.
    bob_etag = _etag(client, auth_headers(bob))
    alice_etag = _etag(client, auth_headers(alice))
    assert bob_etag != alice_etag
    response = client.get(
        "/api/sync/snapshot", headers={**auth_headers(bob), "If-None-Match": alice_etag}
    )
    assert response.status_code == 200


def test_if_none_match_accepts_weak_validators_lists_and_star(
    client: TestClient, make_user, auth_headers
) -> None:
    headers = auth_headers(make_user())
    etag = _etag(client, headers)

    for value in (f"W/{etag}", f'"nope", {etag}', "*"):
        response = client.get("/api/sync/snapshot", headers={**headers, "If-None-Match": value})
        assert response.status_code == 304, value
