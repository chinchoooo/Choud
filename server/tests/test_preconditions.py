"""Compare-and-swap uploads and deletes (`base_version_id`), used by sync clients."""

import pytest
from fastapi.testclient import TestClient

from app.services.errors import ValidationError
from app.services.version_service import parse_base_version


def _upload(client: TestClient, headers: dict, name="doc.txt", content=b"v1", **form):
    return client.post(
        "/api/files/upload",
        files={"file": (name, content, "text/plain")},
        data={k: v for k, v in form.items() if v is not None},
        headers=headers,
    )


def _current_version_id(client: TestClient, headers: dict, file_id: str) -> str:
    versions = client.get(f"/api/files/{file_id}/versions", headers=headers).json()["versions"]
    return next(v["id"] for v in versions if v["is_current"])


def test_parse_base_version() -> None:
    assert parse_base_version(None) == (None, False)
    assert parse_base_version("") == (None, False)
    assert parse_base_version("none") == (None, True)
    base, expect_new = parse_base_version("6f1c1b7e-0c1f-4a55-9d6f-2f6d3f0c7d11")
    assert str(base) == "6f1c1b7e-0c1f-4a55-9d6f-2f6d3f0c7d11" and not expect_new
    with pytest.raises(ValidationError):
        parse_base_version("not-a-uuid")


def test_upload_with_the_current_base_version_succeeds(
    client: TestClient, make_user, auth_headers
) -> None:
    headers = auth_headers(make_user())
    first = _upload(client, headers, content=b"one").json()
    base = _current_version_id(client, headers, first["id"])

    response = _upload(client, headers, content=b"two", base_version_id=base)

    assert response.status_code == 201
    assert response.json()["id"] == first["id"]
    assert response.json()["size"] == 3


def test_upload_with_a_stale_base_version_is_a_structured_409_and_changes_nothing(
    client: TestClient, make_user, auth_headers
) -> None:
    headers = auth_headers(make_user())
    first = _upload(client, headers, content=b"one").json()
    stale = _current_version_id(client, headers, first["id"])
    _upload(client, headers, content=b"two, edited elsewhere")  # someone else moves on
    current = _current_version_id(client, headers, first["id"])

    response = _upload(client, headers, content=b"my offline edit", base_version_id=stale)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "version_conflict"
    assert detail["file_id"] == first["id"]
    assert detail["current_version_id"] == current
    # Nothing was overwritten or added.
    versions = client.get(f"/api/files/{first['id']}/versions", headers=headers).json()
    assert len(versions["versions"]) == 2
    download = client.get(f"/api/files/{first['id']}/download", headers=headers)
    assert download.content == b"two, edited elsewhere"


def test_identical_content_is_never_a_conflict_even_with_a_stale_base(
    client: TestClient, make_user, auth_headers
) -> None:
    headers = auth_headers(make_user())
    first = _upload(client, headers, content=b"one").json()
    stale = _current_version_id(client, headers, first["id"])
    _upload(client, headers, content=b"converged content")

    # The other side already holds exactly what this client wants to write.
    response = _upload(client, headers, content=b"converged content", base_version_id=stale)

    assert response.status_code == 201


def test_none_means_create_only(client: TestClient, make_user, auth_headers) -> None:
    headers = auth_headers(make_user())

    created = _upload(client, headers, name="new.txt", content=b"a", base_version_id="none")
    assert created.status_code == 201

    clash = _upload(client, headers, name="new.txt", content=b"b", base_version_id="none")
    assert clash.status_code == 409
    assert clash.json()["detail"]["code"] == "version_conflict"


def test_base_version_for_a_file_deleted_elsewhere_recreates_it_instead_of_dropping_data(
    client: TestClient, make_user, auth_headers
) -> None:
    headers = auth_headers(make_user())
    first = _upload(client, headers, content=b"one").json()
    base = _current_version_id(client, headers, first["id"])
    client.delete(f"/api/files/{first['id']}", headers=headers)  # deleted on another device

    response = _upload(client, headers, content=b"edited offline", base_version_id=base)

    assert response.status_code == 201
    assert response.json()["id"] != first["id"]  # a fresh file; the trashed one is untouched
    assert response.json()["size"] == len(b"edited offline")


def test_malformed_base_version_is_a_422(client: TestClient, make_user, auth_headers) -> None:
    headers = auth_headers(make_user())

    response = _upload(client, headers, base_version_id="garbage")

    assert response.status_code == 422


def test_delete_with_the_current_base_version_trashes_the_file(
    client: TestClient, make_user, auth_headers
) -> None:
    headers = auth_headers(make_user())
    f = _upload(client, headers).json()
    base = _current_version_id(client, headers, f["id"])

    response = client.delete(
        f"/api/files/{f['id']}", params={"base_version_id": base}, headers=headers
    )

    assert response.status_code == 204
    assert [t["id"] for t in client.get("/api/trash", headers=headers).json()["files"]] == [f["id"]]


def test_delete_with_a_stale_base_version_is_refused_and_keeps_the_file(
    client: TestClient, make_user, auth_headers
) -> None:
    headers = auth_headers(make_user())
    f = _upload(client, headers, content=b"one").json()
    stale = _current_version_id(client, headers, f["id"])
    _upload(client, headers, content=b"edited on another device")

    response = client.delete(
        f"/api/files/{f['id']}", params={"base_version_id": stale}, headers=headers
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "version_conflict"
    assert client.get(f"/api/files/{f['id']}", headers=headers).status_code == 200


def test_delete_without_a_base_version_still_works_unconditionally(
    client: TestClient, make_user, auth_headers
) -> None:
    headers = auth_headers(make_user())
    f = _upload(client, headers).json()

    assert client.delete(f"/api/files/{f['id']}", headers=headers).status_code == 204


# --- chunked uploads --------------------------------------------------------


def _chunked(client: TestClient, headers: dict, name: str, content: bytes, **session):
    created = client.post(
        "/api/uploads",
        json={"file_name": name, "file_size": len(content), "chunk_size": 10, **session},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    upload_id = created.json()["id"]
    for i in range(0, len(content), 10):
        client.post(
            f"/api/uploads/{upload_id}/chunks/{i // 10}",
            files={"chunk": ("c", content[i : i + 10], "application/octet-stream")},
            headers=headers,
        )
    return upload_id, client.post(f"/api/uploads/{upload_id}/complete", headers=headers)


def test_chunked_upload_honours_the_base_version(
    client: TestClient, make_user, auth_headers
) -> None:
    headers = auth_headers(make_user())
    f = _upload(client, headers, name="big.bin", content=b"small").json()
    base = _current_version_id(client, headers, f["id"])

    _, done = _chunked(client, headers, "big.bin", b"B" * 35, base_version_id=base)

    assert done.status_code == 200
    assert done.json()["id"] == f["id"]


def test_chunked_upload_with_a_stale_base_conflicts_and_aborts_the_session(
    client: TestClient, make_user, auth_headers
) -> None:
    headers = auth_headers(make_user())
    f = _upload(client, headers, name="big.bin", content=b"small").json()
    stale = _current_version_id(client, headers, f["id"])
    _upload(client, headers, name="big.bin", content=b"changed on another device")

    upload_id, done = _chunked(client, headers, "big.bin", b"B" * 35, base_version_id=stale)

    assert done.status_code == 409
    assert done.json()["detail"]["code"] == "version_conflict"
    status = client.get(f"/api/uploads/{upload_id}", headers=headers).json()
    assert status["status"] == "aborted"  # can't be re-completed with consumed chunks
    # The file still has the other device's content.
    download = client.get(f"/api/files/{f['id']}/download", headers=headers)
    assert download.content == b"changed on another device"


def test_chunked_upload_rejects_a_malformed_base_version_up_front(
    client: TestClient, make_user, auth_headers
) -> None:
    headers = auth_headers(make_user())

    response = client.post(
        "/api/uploads",
        json={"file_name": "x.bin", "file_size": 10, "chunk_size": 10, "base_version_id": "nope"},
        headers=headers,
    )

    assert response.status_code == 422
