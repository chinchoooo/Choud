"""Edit links (Phase 12): visitors with an edit link can add and change files, nothing else."""

import pytest
from fastapi.testclient import TestClient

from app.core import rate_limit
from app.models.user import User


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    rate_limit.reset()
    yield
    rate_limit.reset()


def _upload(client, headers, name, data=b"hello", folder_id=None):
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


def _edit_folder_share(client, headers, path="Team", **extra):
    root = _folder(client, headers, path)
    share = _share(client, headers, folder_id=root, permission="edit", **extra)
    return root, share["url_path"]


def _listing(client, headers, folder_id):
    return client.get(f"/api/files?folder_id={folder_id}", headers=headers).json()


def test_links_are_view_only_by_default_and_permission_can_change(
    client: TestClient, make_user, auth_headers
):
    headers = auth_headers(make_user())
    root = _folder(client, headers, "Box")
    share = _share(client, headers, folder_id=root)
    assert share["permission"] == "view"
    changed = client.patch(
        f"/api/shares/{share['id']}", json={"permission": "edit"}, headers=headers
    )
    assert changed.json()["permission"] == "edit"
    bad = client.patch(f"/api/shares/{share['id']}", json={"permission": "own"}, headers=headers)
    assert bad.status_code == 422
    made = client.post("/api/shares", json={"folder_id": root, "permission": "x"}, headers=headers)
    assert made.status_code == 422


def test_a_view_only_link_rejects_every_edit(client: TestClient, make_user, auth_headers):
    headers = auth_headers(make_user())
    root = _folder(client, headers, "Box")
    file = _upload(client, headers, "a.txt", b"a", folder_id=root)
    url = _share(client, headers, folder_id=root)["url_path"]
    assert "ADD FILES" not in client.get(url).text
    posts = [
        ("upload", {"files": ("x.txt", b"x")}, {}),
        ("mkdir", None, {"name": "new"}),
        ("rename", None, {"file_id": file["id"], "name": "b.txt"}),
        ("trash", None, {"file_id": file["id"]}),
    ]
    for action, files, data in posts:
        response = client.post(f"{url}/{action}", files=files, data=data, follow_redirects=False)
        assert response.status_code == 403, action
    listing = _listing(client, headers, root)
    assert [f["name"] for f in listing["files"]] == ["a.txt"]
    assert listing["subfolders"] == []


def test_an_edit_link_can_add_files_make_folders_rename_and_trash(
    client: TestClient, make_user, auth_headers
):
    headers = auth_headers(make_user())
    root, url = _edit_folder_share(client, headers)
    existing = _upload(client, headers, "old.txt", b"old", folder_id=root)
    assert "ADD FILES" in client.get(url).text

    added = client.post(
        f"{url}/upload",
        files=[("files", ("one.txt", b"1")), ("files", ("two.txt", b"22"))],
        data={"folder": ""},
        follow_redirects=False,
    )
    assert added.status_code == 303 and added.headers["location"] == url

    made = client.post(f"{url}/mkdir", data={"parent": "", "name": "Sub"}, follow_redirects=False)
    assert made.status_code == 303
    listing = _listing(client, headers, root)
    assert sorted(f["name"] for f in listing["files"]) == ["old.txt", "one.txt", "two.txt"]
    sub = listing["subfolders"][0]["id"]

    in_sub = client.post(
        f"{url}/upload",
        files={"files": ("deep.txt", b"d")},
        data={"folder": sub},
        follow_redirects=False,
    )
    assert in_sub.status_code == 303 and in_sub.headers["location"] == f"{url}?folder={sub}"

    renamed = client.post(
        f"{url}/rename",
        data={"file_id": existing["id"], "name": "new.txt"},
        follow_redirects=False,
    )
    assert renamed.status_code == 303
    trashed = client.post(f"{url}/trash", data={"file_id": existing["id"]}, follow_redirects=False)
    assert trashed.status_code == 303
    # Deleted through a link = in the owner's trash, restorable, not gone.
    trash = client.get("/api/trash", headers=headers).json()["files"]
    assert [t["name"] for t in trash] == ["new.txt"]


def test_a_same_name_upload_through_an_edit_link_adds_a_version(
    client: TestClient, make_user, auth_headers
):
    headers = auth_headers(make_user())
    root, url = _edit_folder_share(client, headers)
    file = _upload(client, headers, "doc.txt", b"v1", folder_id=root)
    client.post(f"{url}/upload", files={"files": ("doc.txt", b"v2 longer")}, data={"folder": ""})
    versions = client.get(f"/api/files/{file['id']}/versions", headers=headers).json()
    assert len(versions) == 2


def test_an_edit_link_cannot_touch_anything_outside_its_folder(
    client: TestClient, make_user, auth_headers
):
    headers = auth_headers(make_user())
    root, url = _edit_folder_share(client, headers)
    elsewhere = _folder(client, headers, "Elsewhere")
    outside = _upload(client, headers, "secret.txt", b"s", folder_id=elsewhere)
    at_root = _upload(client, headers, "top.txt", b"t")

    attempts = [
        ("upload", {"files": ("x.txt", b"x")}, {"folder": elsewhere}),
        ("upload", {"files": ("x.txt", b"x")}, {"folder": "not-a-uuid"}),
        ("mkdir", None, {"parent": elsewhere, "name": "n"}),
        ("rename", None, {"file_id": outside["id"], "name": "pwn.txt"}),
        ("trash", None, {"file_id": outside["id"]}),
        ("trash", None, {"file_id": at_root["id"]}),
    ]
    for action, files, data in attempts:
        response = client.post(f"{url}/{action}", files=files, data=data, follow_redirects=False)
        assert response.status_code == 404, (action, data)
    assert [f["name"] for f in _listing(client, headers, elsewhere)["files"]] == ["secret.txt"]
    assert client.get("/api/trash", headers=headers).json()["files"] == []


def test_an_edit_link_on_a_file_can_only_replace_that_file(
    client: TestClient, make_user, auth_headers
):
    headers = auth_headers(make_user())
    file = _upload(client, headers, "report.txt", b"v1")
    url = _share(client, headers, file_id=file["id"], permission="edit")["url_path"]
    assert "UPLOAD NEW VERSION" in client.get(url).text
    done = client.post(
        f"{url}/upload", files={"files": ("whatever.bin", b"v2!")}, follow_redirects=False
    )
    assert done.status_code == 303
    assert len(client.get(f"/api/files/{file['id']}/versions", headers=headers).json()) == 2
    assert client.get(f"/api/files/{file['id']}", headers=headers).json()["name"] == "report.txt"
    assert client.post(f"{url}/mkdir", data={"name": "x"}).status_code == 403
    assert client.post(f"{url}/trash", data={"file_id": file["id"]}).status_code == 403
    two = client.post(f"{url}/upload", files=[("files", ("a", b"1")), ("files", ("b", b"2"))])
    assert two.status_code == 422


def test_a_password_protected_edit_link_needs_the_unlock_first(
    client: TestClient, make_user, auth_headers
):
    headers = auth_headers(make_user())
    root, url = _edit_folder_share(client, headers, password="hunter22")
    blocked = client.post(f"{url}/upload", files={"files": ("x.txt", b"x")}, follow_redirects=False)
    assert blocked.status_code != 303
    assert _listing(client, headers, root)["files"] == []
    client.post(f"{url}/unlock", data={"password": "hunter22"})
    ok = client.post(f"{url}/upload", files={"files": ("x.txt", b"x")}, follow_redirects=False)
    assert ok.status_code == 303


def test_edit_links_refuse_bad_input_with_a_page_not_a_crash(
    client: TestClient, make_user, auth_headers
):
    headers = auth_headers(make_user())
    root, url = _edit_folder_share(client, headers)
    _upload(client, headers, "a.txt", b"a", folder_id=root)
    b = _upload(client, headers, "b.txt", b"b", folder_id=root)
    many = [("files", (f"f{i}.txt", b"x")) for i in range(21)]
    assert client.post(f"{url}/upload", files=many, data={"folder": ""}).status_code == 422
    assert client.post(f"{url}/mkdir", data={"name": "../x"}).status_code == 422
    assert client.post(f"{url}/mkdir", data={"name": "  "}).status_code == 422
    dup = client.post(f"{url}/mkdir", data={"name": "Dup"}, follow_redirects=False)
    assert dup.status_code == 303
    assert client.post(f"{url}/mkdir", data={"name": "Dup"}).status_code == 409
    clash = client.post(f"{url}/rename", data={"file_id": b["id"], "name": "a.txt"})
    assert clash.status_code == 409
    bad = client.post(f"{url}/rename", data={"file_id": b["id"], "name": "../etc"})
    assert bad.status_code == 422


def test_edit_uploads_are_stopped_by_the_owners_quota(
    client: TestClient, make_user, auth_headers, db_session
):
    user = make_user()
    headers = auth_headers(user)
    _, url = _edit_folder_share(client, headers)
    row = db_session.get(User, user.id)
    row.storage_quota = 3
    db_session.commit()
    response = client.post(f"{url}/upload", files={"files": ("big.txt", b"123456789")})
    assert response.status_code == 413
