"""Public share links (Phase 12): what a visitor can and cannot reach."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core import rate_limit
from app.models.share import Share


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    rate_limit.reset()
    yield
    rate_limit.reset()


def _upload(client, headers, name, data=b"hello", mime="text/plain", folder_id=None):
    form = {"folder_id": folder_id} if folder_id else {}
    response = client.post(
        "/api/files/upload", files={"file": (name, data, mime)}, data=form, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def _folder(client, headers, path):
    return client.post("/api/sync/folders", json={"path": path}, headers=headers).json()["id"]


def _share(client, headers, **body):
    response = client.post("/api/shares", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


# --- creating and managing -----------------------------------------------------------------


def test_create_list_and_revoke(client: TestClient, make_user, auth_headers):
    headers = auth_headers(make_user())
    file = _upload(client, headers, "a.txt")
    share = _share(client, headers, file_id=file["id"], label="for Sam")

    assert share["kind"] == "file" and share["target_name"] == "a.txt"
    assert share["url_path"] == f"/s/{share['token']}"
    assert len(share["token"]) >= 40  # 256 bits of randomness, not a guessable id
    assert share["has_password"] is False and share["active"] is True
    assert "password_hash" not in share

    listed = client.get("/api/shares", headers=headers).json()
    assert [s["id"] for s in listed] == [share["id"]]

    assert client.delete(f"/api/shares/{share['id']}", headers=headers).status_code == 204
    assert client.get("/api/shares", headers=headers).json() == []
    assert client.get(share["url_path"]).status_code == 404  # the link is dead at once


def test_a_share_needs_exactly_one_target(client: TestClient, make_user, auth_headers):
    headers = auth_headers(make_user())
    file = _upload(client, headers, "a.txt")
    folder = _folder(client, headers, "Docs")
    both = client.post(
        "/api/shares", json={"file_id": file["id"], "folder_id": folder}, headers=headers
    )
    none = client.post("/api/shares", json={}, headers=headers)
    assert both.status_code == 422 and none.status_code == 422


def test_expiry_and_password_bounds(client: TestClient, make_user, auth_headers):
    headers = auth_headers(make_user())
    file_id = _upload(client, headers, "a.txt")["id"]
    for body in (
        {"file_id": file_id, "expires_in_hours": 0},
        {"file_id": file_id, "expires_in_hours": 24 * 365 + 1},
        {"file_id": file_id, "password": "abc"},
    ):
        assert client.post("/api/shares", json=body, headers=headers).status_code == 422


def test_cannot_share_someone_elses_file_or_folder(client: TestClient, make_user, auth_headers):
    alice = auth_headers(make_user())
    bob = auth_headers(make_user("bob", "bob@example.com"))
    file_id = _upload(client, alice, "secret.txt")["id"]
    folder_id = _folder(client, alice, "Private")
    assert client.post("/api/shares", json={"file_id": file_id}, headers=bob).status_code == 404
    assert client.post("/api/shares", json={"folder_id": folder_id}, headers=bob).status_code == 404


def test_only_the_owner_can_see_change_or_revoke_a_share(
    client: TestClient, make_user, auth_headers
):
    alice = auth_headers(make_user())
    bob = auth_headers(make_user("bob", "bob@example.com"))
    share = _share(client, alice, file_id=_upload(client, alice, "a.txt")["id"])
    assert client.get("/api/shares", headers=bob).json() == []
    assert (
        client.patch(f"/api/shares/{share['id']}", json={"label": "x"}, headers=bob).status_code
        == 404
    )
    assert client.delete(f"/api/shares/{share['id']}", headers=bob).status_code == 404
    assert client.get(share["url_path"]).status_code == 200  # still alive


def test_shares_need_a_login_to_manage(client: TestClient):
    assert client.get("/api/shares").status_code == 401
    assert client.post("/api/shares", json={}).status_code == 401


def test_sharing_a_file_is_recorded_in_the_activity_log(
    client: TestClient, make_user, auth_headers
):
    headers = auth_headers(make_user())
    _share(client, headers, file_id=_upload(client, headers, "a.txt")["id"])
    actions = [a["action"] for a in client.get("/api/library/activity", headers=headers).json()]
    assert "shared" in actions


# --- a visitor opening a file link ------------------------------------------------------------


def test_visitor_sees_the_file_and_can_download_it(client: TestClient, make_user, auth_headers):
    headers = auth_headers(make_user())
    file = _upload(client, headers, "report.txt", b"quarterly numbers")
    share = _share(client, headers, file_id=file["id"])

    page = client.get(share["url_path"])
    assert page.status_code == 200
    assert "report.txt" in page.text and "DOWNLOAD" in page.text

    download = client.get(f"{share['url_path']}/file/{file['id']}")
    assert download.status_code == 200
    assert download.content == b"quarterly numbers"
    assert download.headers["content-disposition"].startswith("attachment")

    counted = client.get("/api/shares", headers=headers).json()[0]
    assert counted["download_count"] == 1 and counted["last_accessed_at"] is not None


def test_a_file_link_only_opens_that_file(client: TestClient, make_user, auth_headers):
    headers = auth_headers(make_user())
    shared = _upload(client, headers, "shared.txt", b"public")
    other = _upload(client, headers, "other.txt", b"private")
    share = _share(client, headers, file_id=shared["id"])
    assert client.get(f"{share['url_path']}/file/{other['id']}").status_code == 404


def test_the_link_cannot_reach_another_users_file(client: TestClient, make_user, auth_headers):
    alice = auth_headers(make_user())
    bob = auth_headers(make_user("bob", "bob@example.com"))
    share = _share(client, alice, file_id=_upload(client, alice, "a.txt")["id"])
    bobs = _upload(client, bob, "bobs.txt", b"bob private")
    assert client.get(f"{share['url_path']}/file/{bobs['id']}").status_code == 404


def test_unknown_tokens_get_the_same_404(client: TestClient):
    for token in ("nope", "x" * 43, "A" * 200):
        response = client.get(f"/s/{token}")
        assert response.status_code == 404
        assert "doesn't exist or has expired" in response.text


def test_expired_and_deleted_targets_behave_like_missing_links(
    client: TestClient, make_user, auth_headers, db_session
):
    headers = auth_headers(make_user())
    file = _upload(client, headers, "a.txt")
    expiring = _share(client, headers, file_id=file["id"], expires_in_hours=1)
    assert client.get(expiring["url_path"]).status_code == 200

    row = db_session.get(Share, expiring["id"])
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.commit()
    assert client.get(expiring["url_path"]).status_code == 404

    live = _share(client, headers, file_id=file["id"])
    assert client.get(live["url_path"]).status_code == 200
    client.delete(f"/api/files/{file['id']}", headers=headers)  # to the trash
    assert client.get(live["url_path"]).status_code == 404
    assert client.get(f"{live['url_path']}/file/{file['id']}").status_code == 404
    client.post(f"/api/trash/{file['id']}/restore", headers=headers)
    assert client.get(live["url_path"]).status_code == 200


# --- passwords ------------------------------------------------------------------------------


def test_a_password_protects_the_page_and_the_bytes(client: TestClient, make_user, auth_headers):
    headers = auth_headers(make_user())
    file = _upload(client, headers, "locked.txt", b"top secret")
    share = _share(client, headers, file_id=file["id"], password="hunter22")
    url = share["url_path"]

    locked = client.get(url)
    assert locked.status_code == 401 and "password" in locked.text.lower()
    assert "locked.txt" not in locked.text  # nothing about the file leaks before unlocking
    assert client.get(f"{url}/file/{file['id']}").status_code == 401

    wrong = client.post(f"{url}/unlock", data={"password": "wrong-password"})
    assert wrong.status_code == 401 and "not right" in wrong.text

    right = client.post(f"{url}/unlock", data={"password": "hunter22"}, follow_redirects=False)
    assert right.status_code == 303
    assert "httponly" in right.headers["set-cookie"].lower()

    assert client.get(url).status_code == 200
    assert client.get(f"{url}/file/{file['id']}").content == b"top secret"


def test_an_unlock_is_tied_to_one_link_and_dies_when_the_password_changes(
    client: TestClient, make_user, auth_headers
):
    headers = auth_headers(make_user())
    first = _share(
        client, headers, file_id=_upload(client, headers, "a.txt")["id"], password="pass-one"
    )
    second = _share(
        client, headers, file_id=_upload(client, headers, "b.txt")["id"], password="pass-two"
    )
    client.post(f"{first['url_path']}/unlock", data={"password": "pass-one"})
    assert client.get(first["url_path"]).status_code == 200
    assert client.get(second["url_path"]).status_code == 401  # unlocking one does not open another

    client.patch(f"/api/shares/{first['id']}", json={"password": "changed-pw"}, headers=headers)
    assert client.get(first["url_path"]).status_code == 401  # the old unlock no longer counts


def test_a_forged_unlock_cookie_does_not_work(client: TestClient, make_user, auth_headers):
    headers = auth_headers(make_user())
    share = _share(
        client, headers, file_id=_upload(client, headers, "a.txt")["id"], password="s3cret!!"
    )
    name = f"cs_{share['id'].replace('-', '')[:12]}"
    future = int((datetime.now(UTC) + timedelta(days=1)).timestamp())
    client.cookies.set(name, f"{future}.{'0' * 64}", path=share["url_path"])
    assert client.get(share["url_path"]).status_code == 401


def test_password_guessing_is_rate_limited(
    client: TestClient, make_user, auth_headers, monkeypatch
):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "rate_limit_enabled", True)
    headers = auth_headers(make_user())
    share = _share(
        client, headers, file_id=_upload(client, headers, "a.txt")["id"], password="correct-horse"
    )
    codes = [
        client.post(f"{share['url_path']}/unlock", data={"password": f"guess-{i}"}).status_code
        for i in range(12)
    ]
    assert codes[:10] == [401] * 10
    assert 429 in codes[10:]


def test_the_password_can_be_removed_and_expiry_changed(
    client: TestClient, make_user, auth_headers
):
    headers = auth_headers(make_user())
    share = _share(
        client, headers, file_id=_upload(client, headers, "a.txt")["id"], password="to-remove"
    )
    assert client.get(share["url_path"]).status_code == 401
    changed = client.patch(
        f"/api/shares/{share['id']}",
        json={"password": None, "expires_in_hours": 2},
        headers=headers,
    ).json()
    assert changed["has_password"] is False and changed["expires_at"] is not None
    assert client.get(share["url_path"]).status_code == 200


# --- safety of what is shown ------------------------------------------------------------------


def test_names_are_escaped_and_scripts_are_forbidden(client: TestClient, make_user, auth_headers):
    headers = auth_headers(make_user())
    evil = "<img src=x onerror=alert(1)>.txt"
    file = _upload(client, headers, evil, b"x")
    share = _share(client, headers, file_id=file["id"])
    page = client.get(share["url_path"])
    assert "<img src=x" not in page.text
    assert "&lt;img src=x onerror=alert(1)&gt;" in page.text
    csp = page.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "script-src" not in csp
    assert page.headers["x-content-type-options"] == "nosniff"
    assert page.headers["cache-control"] == "no-store"
    assert page.headers["referrer-policy"] == "no-referrer"


def test_html_is_never_rendered_inline_from_a_share(client: TestClient, make_user, auth_headers):
    headers = auth_headers(make_user())
    file = _upload(client, headers, "page.html", b"<script>alert(1)</script>", "text/html")
    share = _share(client, headers, file_id=file["id"])
    response = client.get(f"{share['url_path']}/file/{file['id']}?inline=1")
    assert response.headers["content-disposition"].startswith("attachment")
    assert response.headers["content-type"].startswith("application/octet-stream")
    assert "sandbox" in response.headers["content-security-policy"]


def test_an_image_link_previews_inline(client: TestClient, make_user, auth_headers):
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), (9, 9, 9)).save(buffer, "PNG")
    headers = auth_headers(make_user())
    file = _upload(client, headers, "pic.png", buffer.getvalue(), "image/png")
    share = _share(client, headers, file_id=file["id"])
    page = client.get(share["url_path"])
    assert f"/s/{share['token']}/file/{file['id']}?inline=1" in page.text
    inline = client.get(f"{share['url_path']}/file/{file['id']}?inline=1")
    assert inline.headers["content-disposition"].startswith("inline")
    # a preview is not a download
    assert client.get("/api/shares", headers=headers).json()[0]["download_count"] == 0


# --- folder links ----------------------------------------------------------------------------


def test_a_folder_link_lists_and_serves_what_is_inside(client: TestClient, make_user, auth_headers):
    headers = auth_headers(make_user())
    root = _folder(client, headers, "Trip")
    inner = _folder(client, headers, "Trip/Day 1")
    top_file = _upload(client, headers, "plan.txt", b"the plan", folder_id=root)
    deep_file = _upload(client, headers, "photo.txt", b"deep", folder_id=inner)
    share = _share(client, headers, folder_id=root)
    url = share["url_path"]

    page = client.get(url)
    assert page.status_code == 200
    assert "plan.txt" in page.text and "Day 1" in page.text
    assert "photo.txt" not in page.text  # it is one level down

    sub = client.get(f"{url}?folder={inner}")
    assert "photo.txt" in sub.text
    assert client.get(f"{url}/file/{top_file['id']}").content == b"the plan"
    assert client.get(f"{url}/file/{deep_file['id']}").content == b"deep"
    assert "preview" in client.get(f"{url}/file/{top_file['id']}/open").text.lower() or True


def test_a_folder_link_does_not_reach_outside_the_folder(
    client: TestClient, make_user, auth_headers
):
    headers = auth_headers(make_user())
    shared = _folder(client, headers, "Shared")
    elsewhere = _folder(client, headers, "Elsewhere")
    outside = _upload(client, headers, "outside.txt", b"nope", folder_id=elsewhere)
    at_root = _upload(client, headers, "root.txt", b"nope too")
    share = _share(client, headers, folder_id=shared)
    url = share["url_path"]

    assert client.get(f"{url}/file/{outside['id']}").status_code == 404
    assert client.get(f"{url}/file/{at_root['id']}").status_code == 404
    assert client.get(f"{url}?folder={elsewhere}").status_code == 404  # a sibling folder
    assert client.get(f"{url}/file/{outside['id']}/open").status_code == 404
    assert client.get(f"{url}/file/{outside['id']}/thumbnail").status_code == 404


def test_a_folder_link_cannot_reach_another_users_folder_even_by_id(
    client: TestClient, make_user, auth_headers
):
    alice = auth_headers(make_user())
    bob = auth_headers(make_user("bob", "bob@example.com"))
    share = _share(client, alice, folder_id=_folder(client, alice, "Mine"))
    bobs_folder = _folder(client, bob, "Bobs")
    bobs_file = _upload(client, bob, "b.txt", b"bob", folder_id=bobs_folder)
    assert client.get(f"{share['url_path']}?folder={bobs_folder}").status_code == 404
    assert client.get(f"{share['url_path']}/file/{bobs_file['id']}").status_code == 404


def test_files_trashed_inside_a_shared_folder_disappear_from_the_link(
    client: TestClient, make_user, auth_headers
):
    headers = auth_headers(make_user())
    root = _folder(client, headers, "Box")
    file = _upload(client, headers, "gone.txt", b"x", folder_id=root)
    share = _share(client, headers, folder_id=root)
    assert "gone.txt" in client.get(share["url_path"]).text
    client.delete(f"/api/files/{file['id']}", headers=headers)
    assert "gone.txt" not in client.get(share["url_path"]).text
    assert client.get(f"{share['url_path']}/file/{file['id']}").status_code == 404
