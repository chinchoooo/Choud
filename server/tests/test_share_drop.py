"""File-request (drop) links and download-limited links."""

import pytest
from fastapi.testclient import TestClient

from app.core import rate_limit
from app.models.user import User


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    rate_limit.reset()
    yield
    rate_limit.reset()


def _upload(client, headers, name, data=b"x", folder_id=None):
    form = {"folder_id": folder_id} if folder_id else {}
    response = client.post(
        "/api/files/upload", files={"file": (name, data, "text/plain")}, data=form, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def _folder(client, headers, path):
    return client.post("/api/sync/folders", json={"path": path}, headers=headers).json()["id"]


def _share(client, headers, **body):
    response = client.post("/api/shares", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _names(client, headers, folder):
    listing = client.get(f"/api/files?folder_id={folder}", headers=headers).json()
    return sorted(f["name"] for f in listing["files"])


def test_a_drop_link_only_takes_files_and_shows_nothing(
    client: TestClient, make_user, auth_headers
) -> None:
    headers = auth_headers(make_user())
    folder = _folder(client, headers, "Requests")
    existing = _upload(client, headers, "private-plan.txt", b"secret", folder)
    share = _share(client, headers, folder_id=folder, permission="drop")
    url = share["url_path"]

    page = client.get(url)
    assert page.status_code == 200
    assert "SEND FILES" in page.text and "private-plan.txt" not in page.text

    sent = client.post(
        url + "/upload",
        files=[("files", ("cv.txt", b"my cv")), ("files", ("photo.txt", b"pic"))],
        follow_redirects=False,
    )
    assert sent.status_code == 303 and sent.headers["location"] == f"{url}?sent=2"
    assert "2 files sent" in client.get(f"{url}?sent=2").text
    assert _names(client, headers, folder) == ["cv.txt", "photo.txt", "private-plan.txt"]

    # Visitors cannot read, preview, thumbnail or change anything that is already there.
    assert client.get(f"{url}/file/{existing['id']}").status_code == 404
    assert client.get(f"{url}/file/{existing['id']}/open").status_code == 404
    assert client.get(f"{url}/file/{existing['id']}/thumbnail").status_code == 404
    assert client.post(f"{url}/mkdir", data={"name": "x"}).status_code == 403
    assert client.post(f"{url}/trash", data={"file_id": existing["id"]}).status_code == 403
    rename = client.post(f"{url}/rename", data={"file_id": existing["id"], "name": "pwn.txt"})
    assert rename.status_code == 403


def test_a_drop_never_overwrites_it_renames(client: TestClient, make_user, auth_headers) -> None:
    headers = auth_headers(make_user())
    folder = _folder(client, headers, "Requests")
    original = _upload(client, headers, "report.pdf", b"the real one", folder)
    url = _share(client, headers, folder_id=folder, permission="drop")["url_path"]

    for content in (b"visitor one", b"visitor two"):
        client.post(url + "/upload", files={"files": ("report.pdf", content)})

    assert _names(client, headers, folder) == ["report (2).pdf", "report (3).pdf", "report.pdf"]
    kept = client.get(f"/api/files/{original['id']}/download", headers=headers).content
    assert kept == b"the real one"  # untouched, and no new version was added
    versions = client.get(f"/api/files/{original['id']}/versions", headers=headers).json()
    assert len(versions["versions"]) == 1


def test_a_drop_link_needs_a_folder_and_respects_limits(
    client: TestClient, make_user, auth_headers, db_session
) -> None:
    user = make_user()
    headers = auth_headers(user)
    file = _upload(client, headers, "a.txt")
    bad = client.post(
        "/api/shares", json={"file_id": file["id"], "permission": "drop"}, headers=headers
    )
    assert bad.status_code == 422

    folder = _folder(client, headers, "Requests")
    plain = _share(client, headers, folder_id=folder)
    changed = client.patch(
        f"/api/shares/{plain['id']}", json={"permission": "drop"}, headers=headers
    )
    assert changed.json()["permission"] == "drop"

    url = plain["url_path"]
    many = [("files", (f"f{i}.txt", b"x")) for i in range(21)]
    assert client.post(url + "/upload", files=many).status_code == 422
    row = db_session.get(User, user.id)
    row.storage_quota = 2
    db_session.commit()
    assert client.post(url + "/upload", files={"files": ("big.txt", b"123456")}).status_code == 413


def test_a_password_protects_a_drop_link(client: TestClient, make_user, auth_headers) -> None:
    headers = auth_headers(make_user())
    folder = _folder(client, headers, "Requests")
    share = _share(client, headers, folder_id=folder, permission="drop", password="letmein1")
    url = share["url_path"]
    blocked = client.post(url + "/upload", files={"files": ("x.txt", b"x")}, follow_redirects=False)
    assert blocked.status_code != 303 and _names(client, headers, folder) == []
    client.post(url + "/unlock", data={"password": "letmein1"})
    ok = client.post(url + "/upload", files={"files": ("x.txt", b"x")}, follow_redirects=False)
    assert ok.status_code == 303


def test_a_one_time_link_dies_after_its_download(
    client: TestClient, make_user, auth_headers
) -> None:
    headers = auth_headers(make_user())
    file = _upload(client, headers, "once.txt", b"burn after reading")
    share = _share(client, headers, file_id=file["id"], max_downloads=1)
    assert share["max_downloads"] == 1 and share["active"] is True
    url = share["url_path"]

    assert client.get(f"{url}/file/{file['id']}").content == b"burn after reading"
    assert client.get(f"{url}/file/{file['id']}").status_code == 404
    assert client.get(url).status_code == 404  # the whole link is gone, not just the file
    listed = client.get("/api/shares", headers=headers).json()
    assert listed[0]["active"] is False and listed[0]["download_count"] == 1


def test_a_download_limit_can_be_raised_or_removed(
    client: TestClient, make_user, auth_headers
) -> None:
    headers = auth_headers(make_user())
    file = _upload(client, headers, "f.txt")
    share = _share(client, headers, file_id=file["id"], max_downloads=1)
    url = share["url_path"]
    client.get(f"{url}/file/{file['id']}")
    assert client.get(url).status_code == 404

    client.patch(f"/api/shares/{share['id']}", json={"max_downloads": 3}, headers=headers)
    assert client.get(url).status_code == 200  # alive again with room for two more
    client.patch(f"/api/shares/{share['id']}", json={"max_downloads": None}, headers=headers)
    assert client.get(f"{url}/file/{file['id']}").status_code == 200
    zero = client.post(
        "/api/shares", json={"file_id": file["id"], "max_downloads": 0}, headers=headers
    )
    assert zero.status_code == 422
