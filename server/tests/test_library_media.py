"""Phase 11 (favorites, activity, usage, quota) and the media/thumbnail routes."""

import io
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from PIL import Image


def _png(color=(200, 30, 30), size=(640, 480)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def _upload(client, headers, name, content, mime="application/octet-stream", **data):
    return client.post(
        "/api/files/upload",
        files={"file": (name, content, mime)},
        data={k: v for k, v in data.items() if v is not None},
        headers=headers,
    )


def _media_token(client, headers) -> str:
    response = client.post("/api/media/token", headers=headers)
    assert response.status_code == 200
    return response.json()["token"]


# --- media tokens and previews -------------------------------------------------


def test_media_content_needs_a_valid_media_token(client: TestClient, make_user, auth_headers):
    user = make_user()
    headers = auth_headers(user)
    file_id = _upload(client, headers, "a.png", _png(), "image/png").json()["id"]

    assert client.get(f"/api/media/not-a-token/{file_id}/content").status_code == 401
    # An access token is not a media token.
    access = headers["Authorization"].split()[1]
    assert client.get(f"/api/media/{access}/{file_id}/content").status_code == 401

    token = _media_token(client, headers)
    response = client.get(f"/api/media/{token}/{file_id}/content")
    assert response.status_code == 200
    assert response.content == _png()
    assert response.headers["x-content-type-options"] == "nosniff"


def test_media_token_cannot_call_the_normal_api(client: TestClient, make_user, auth_headers):
    user = make_user()
    token = _media_token(client, auth_headers(user))
    response = client.get("/api/files", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_media_is_owner_scoped(client: TestClient, make_user, auth_headers):
    alice = make_user()
    bob = make_user("bob", "bob@example.com")
    file_id = _upload(client, auth_headers(alice), "a.png", _png(), "image/png").json()["id"]
    bob_token = _media_token(client, auth_headers(bob))
    assert client.get(f"/api/media/{bob_token}/{file_id}/content").status_code == 404
    assert client.get(f"/api/media/{bob_token}/{file_id}/thumbnail").status_code == 404


def test_html_is_never_served_inline(client: TestClient, make_user, auth_headers):
    user = make_user()
    headers = auth_headers(user)
    page = b"<html><script>alert(1)</script></html>"
    for name, mime in (("x.html", "text/html"), ("x.svg", "image/svg+xml")):
        file_id = _upload(client, headers, name, page, mime).json()["id"]
        token = _media_token(client, headers)
        response = client.get(f"/api/media/{token}/{file_id}/content")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/octet-stream")
        assert response.headers["content-disposition"].startswith("attachment")
        assert "sandbox" in response.headers["content-security-policy"]


def test_media_content_supports_range_requests(client: TestClient, make_user, auth_headers):
    user = make_user()
    headers = auth_headers(user)
    data = bytes(range(256)) * 40
    file_id = _upload(client, headers, "v.mp4", data, "video/mp4").json()["id"]
    token = _media_token(client, headers)
    response = client.get(
        f"/api/media/{token}/{file_id}/content", headers={"Range": "bytes=100-199"}
    )
    assert response.status_code == 206
    assert response.content == data[100:200]


def test_image_thumbnail_is_a_small_jpeg_and_cached(client: TestClient, make_user, auth_headers):
    user = make_user()
    headers = auth_headers(user)
    file_id = _upload(client, headers, "big.png", _png(size=(2000, 1000)), "image/png").json()["id"]
    token = _media_token(client, headers)

    response = client.get(f"/api/media/{token}/{file_id}/thumbnail?size=256")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    thumb = Image.open(io.BytesIO(response.content))
    assert max(thumb.size) == 256
    assert thumb.size == (256, 128)  # aspect ratio kept

    again = client.get(f"/api/media/{token}/{file_id}/thumbnail?size=256")
    assert again.content == response.content


def test_thumbnail_rejects_odd_sizes_and_non_media(client: TestClient, make_user, auth_headers):
    user = make_user()
    headers = auth_headers(user)
    image_id = _upload(client, headers, "a.png", _png(), "image/png").json()["id"]
    text_id = _upload(client, headers, "a.txt", b"hello", "text/plain").json()["id"]
    token = _media_token(client, headers)
    assert client.get(f"/api/media/{token}/{image_id}/thumbnail?size=99999").status_code == 415
    assert client.get(f"/api/media/{token}/{text_id}/thumbnail").status_code == 415


def test_corrupt_image_gives_a_clean_error_not_a_crash(client: TestClient, make_user, auth_headers):
    user = make_user()
    headers = auth_headers(user)
    file_id = _upload(client, headers, "bad.png", b"this is not a png", "image/png").json()["id"]
    token = _media_token(client, headers)
    assert client.get(f"/api/media/{token}/{file_id}/thumbnail").status_code == 415


# --- library -------------------------------------------------------------------


def test_favorites_round_trip(client: TestClient, make_user, auth_headers):
    user = make_user()
    headers = auth_headers(user)
    file_id = _upload(client, headers, "a.txt", b"a", "text/plain").json()["id"]

    assert client.put(f"/api/library/favorites/{file_id}", headers=headers).status_code == 204
    assert client.put(f"/api/library/favorites/{file_id}", headers=headers).status_code == 204
    favorites = client.get("/api/library/favorites", headers=headers).json()
    assert [f["id"] for f in favorites] == [file_id]
    assert favorites[0]["is_favorite"] is True

    assert client.delete(f"/api/library/favorites/{file_id}", headers=headers).status_code == 204
    assert client.get("/api/library/favorites", headers=headers).json() == []


def test_cannot_favorite_someone_elses_file(client: TestClient, make_user, auth_headers):
    alice = make_user()
    bob = make_user("bob", "bob@example.com")
    file_id = _upload(client, auth_headers(alice), "a.txt", b"a", "text/plain").json()["id"]
    assert (
        client.put(f"/api/library/favorites/{file_id}", headers=auth_headers(bob)).status_code
        == 404
    )


def test_photos_are_sorted_by_taken_at_then_upload_time(
    client: TestClient, make_user, auth_headers
):
    user = make_user()
    headers = auth_headers(user)
    old = (datetime.now(UTC) - timedelta(days=400)).isoformat()
    recent = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    _upload(client, headers, "old.png", _png((1, 1, 1)), "image/png", taken_at=old)
    _upload(client, headers, "recent.png", _png((2, 2, 2)), "image/png", taken_at=recent)
    _upload(client, headers, "notes.txt", b"not a photo", "text/plain")

    page = client.get("/api/library/photos", headers=headers).json()
    assert page["total"] == 2
    assert [f["name"] for f in page["items"]] == ["recent.png", "old.png"]
    assert page["items"][0]["taken_at"] is not None


def test_photos_pagination_and_kind_filter(client: TestClient, make_user, auth_headers):
    user = make_user()
    headers = auth_headers(user)
    for i in range(5):
        _upload(client, headers, f"p{i}.png", _png((i, i, i)), "image/png")
    _upload(client, headers, "v.mp4", b"video", "video/mp4")

    first = client.get("/api/library/photos?limit=2", headers=headers).json()
    assert first["total"] == 6 and len(first["items"]) == 2
    rest = client.get("/api/library/photos?limit=10&offset=2", headers=headers).json()
    assert len(rest["items"]) == 4
    videos = client.get("/api/library/photos?kind=video", headers=headers).json()
    assert [f["name"] for f in videos["items"]] == ["v.mp4"]
    assert client.get("/api/library/photos?kind=evil", headers=headers).status_code == 422


def test_folder_path_is_reported(client: TestClient, make_user, auth_headers):
    user = make_user()
    headers = auth_headers(user)
    folder = client.post("/api/sync/folders", json={"path": "A/B"}, headers=headers).json()
    _upload(client, headers, "x.png", _png(), "image/png", folder_id=folder["id"])
    item = client.get("/api/library/photos", headers=headers).json()["items"][0]
    assert item["folder_path"] == "A/B"


def test_recent_lists_newest_first(client: TestClient, make_user, auth_headers):
    user = make_user()
    headers = auth_headers(user)
    _upload(client, headers, "first.txt", b"1", "text/plain")
    _upload(client, headers, "second.txt", b"2", "text/plain")
    names = [f["name"] for f in client.get("/api/library/recent", headers=headers).json()]
    assert set(names) == {"first.txt", "second.txt"}


def test_activity_records_file_events(client: TestClient, make_user, auth_headers):
    user = make_user()
    headers = auth_headers(user)
    file_id = _upload(client, headers, "a.txt", b"v1", "text/plain").json()["id"]
    _upload(client, headers, "a.txt", b"v2", "text/plain")  # new version
    client.patch(f"/api/files/{file_id}", json={"name": "b.txt"}, headers=headers)
    client.delete(f"/api/files/{file_id}", headers=headers)
    client.post(f"/api/trash/{file_id}/restore", headers=headers)

    actions = [a["action"] for a in client.get("/api/library/activity", headers=headers).json()]
    for expected in ("uploaded", "new_version", "renamed", "trashed", "restored"):
        assert expected in actions


def test_activity_is_private_to_each_user(client: TestClient, make_user, auth_headers):
    alice = make_user()
    bob = make_user("bob", "bob@example.com")
    _upload(client, auth_headers(alice), "a.txt", b"a", "text/plain")
    assert client.get("/api/library/activity", headers=auth_headers(bob)).json() == []


def test_usage_counts_stored_bytes(client: TestClient, make_user, auth_headers):
    user = make_user()
    headers = auth_headers(user)
    _upload(client, headers, "a.bin", b"x" * 1000)
    usage = client.get("/api/library/usage", headers=headers).json()
    assert usage["used_bytes"] == 1000
    assert usage["file_count"] == 1
    assert usage["quota_bytes"] > 1000


# --- quota ---------------------------------------------------------------------


def test_upload_over_quota_is_refused_with_413(
    client: TestClient, make_user, auth_headers, db_session
):
    user = make_user()
    user.storage_quota = 500
    db_session.commit()
    headers = auth_headers(user)

    assert _upload(client, headers, "small.bin", b"x" * 400).status_code == 201
    response = _upload(client, headers, "big.bin", b"y" * 400)
    assert response.status_code == 413
    assert "quota" in response.json()["detail"]


def test_chunked_upload_over_quota_is_refused_up_front(
    client: TestClient, make_user, auth_headers, db_session
):
    user = make_user()
    user.storage_quota = 100
    db_session.commit()
    response = client.post(
        "/api/uploads",
        json={"file_name": "big.bin", "file_size": 5000, "chunk_size": 1000},
        headers=auth_headers(user),
    )
    assert response.status_code == 413


def test_chunked_upload_carries_taken_at(client: TestClient, make_user, auth_headers):
    import hashlib

    user = make_user()
    headers = auth_headers(user)
    data = _png(size=(300, 300))
    taken = "2020-05-17T10:30:00+00:00"
    session = client.post(
        "/api/uploads",
        json={
            "file_name": "p.png",
            "file_size": len(data),
            "chunk_size": len(data),
            "expected_hash": hashlib.sha256(data).hexdigest(),
            "taken_at": taken,
        },
        headers=headers,
    ).json()
    client.post(
        f"/api/uploads/{session['id']}/chunks/0",
        files={"chunk": ("chunk", data, "application/octet-stream")},
        headers=headers,
    )
    done = client.post(f"/api/uploads/{session['id']}/complete", headers=headers)
    assert done.status_code in (200, 201)
    assert done.json()["taken_at"].startswith("2020-05-17")


def test_directory_listing_and_search_report_favorites_and_paths(
    client: TestClient, make_user, auth_headers
):
    user = make_user()
    headers = auth_headers(user)
    folder = client.post("/api/sync/folders", json={"path": "Trips/Italy"}, headers=headers).json()
    uploaded = _upload(client, headers, "rome.png", _png(), "image/png", folder_id=folder["id"])
    file_id = uploaded.json()["id"]
    client.put(f"/api/library/favorites/{file_id}", headers=headers)

    listing = client.get(f"/api/files?folder_id={folder['id']}", headers=headers).json()
    assert listing["files"][0]["is_favorite"] is True
    assert listing["files"][0]["folder_path"] == "Trips/Italy"

    found = client.get("/api/search?q=rome", headers=headers).json()
    assert found["files"][0]["is_favorite"] is True
    assert found["files"][0]["folder_path"] == "Trips/Italy"


def test_new_accounts_get_a_400_gib_quota(client: TestClient):
    response = client.post(
        "/api/auth/register",
        json={"username": "bigdisk", "email": "big@example.com", "password": "password12345"},
    )
    assert response.status_code == 201
    assert response.json()["storage_quota"] == 400 * 1024**3


# --- the device's own dates ------------------------------------------------------


def test_upload_records_the_devices_modified_date(client: TestClient, make_user, auth_headers):
    headers = auth_headers(make_user())
    phone_time = "2024-03-09T18:22:11+00:00"
    uploaded = _upload(client, headers, "a.txt", b"v1", "text/plain", modified_at=phone_time).json()
    assert uploaded["modified_at"].startswith("2024-03-09T18:22:11")
    # the server's own bookkeeping times are unchanged and different
    assert not uploaded["created_at"].startswith("2024-03-09")


def test_a_new_version_updates_the_modified_date(client: TestClient, make_user, auth_headers):
    headers = auth_headers(make_user())
    _upload(client, headers, "a.txt", b"v1", "text/plain", modified_at="2024-01-01T00:00:00+00:00")
    edited = _upload(
        client, headers, "a.txt", b"v2", "text/plain", modified_at="2025-06-06T06:06:06+00:00"
    ).json()
    assert edited["modified_at"].startswith("2025-06-06T06:06:06")


def test_same_bytes_again_still_records_the_date(client: TestClient, make_user, auth_headers):
    headers = auth_headers(make_user())
    first = _upload(client, headers, "a.txt", b"same", "text/plain").json()
    assert first["modified_at"] is None
    again = _upload(
        client, headers, "a.txt", b"same", "text/plain", modified_at="2023-02-02T02:02:02+00:00"
    ).json()
    assert again["id"] == first["id"]
    assert again["modified_at"].startswith("2023-02-02T02:02:02")
    versions = client.get(f"/api/files/{first['id']}/versions", headers=headers).json()
    assert len(versions["versions"]) == 1  # no empty version was created


def test_dates_can_be_fixed_up_on_an_existing_file(client: TestClient, make_user, auth_headers):
    headers = auth_headers(make_user())
    file_id = _upload(client, headers, "p.png", _png(), "image/png").json()["id"]
    response = client.patch(
        f"/api/files/{file_id}",
        json={"modified_at": "2022-12-25T08:00:00+00:00", "taken_at": "2022-12-24T20:00:00+00:00"},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["modified_at"].startswith("2022-12-25T08:00:00")
    assert body["taken_at"].startswith("2022-12-24T20:00:00")
    assert body["name"] == "p.png"  # nothing else changed


def test_cannot_set_dates_on_someone_elses_file(client: TestClient, make_user, auth_headers):
    alice = make_user()
    bob = make_user("bob", "bob@example.com")
    file_id = _upload(client, auth_headers(alice), "a.txt", b"a", "text/plain").json()["id"]
    response = client.patch(
        f"/api/files/{file_id}",
        json={"modified_at": "2020-01-01T00:00:00+00:00"},
        headers=auth_headers(bob),
    )
    assert response.status_code == 404


def test_timeline_prefers_taken_then_modified_then_upload_time(
    client: TestClient, make_user, auth_headers
):
    headers = auth_headers(make_user())
    _upload(
        client,
        headers,
        "taken.png",
        _png((1, 1, 1)),
        "image/png",
        taken_at="2020-01-01T00:00:00+00:00",
        modified_at="2026-01-01T00:00:00+00:00",
    )
    _upload(
        client,
        headers,
        "modified.png",
        _png((2, 2, 2)),
        "image/png",
        modified_at="2021-01-01T00:00:00+00:00",
    )
    _upload(client, headers, "plain.png", _png((3, 3, 3)), "image/png")
    names = [f["name"] for f in client.get("/api/library/photos", headers=headers).json()["items"]]
    # plain = now (newest), modified = 2021, taken = 2020 (taken wins over its newer mtime)
    assert names == ["plain.png", "modified.png", "taken.png"]


# --- thumbnails made ahead of time, and read in place ---------------------------------------------


def test_thumbnails_are_made_ahead_of_time_and_without_copying_the_original(
    client: TestClient, make_user, auth_headers, db_session, monkeypatch
):
    from app.services import file_service, thumbnail_service

    thumbnail_service._settled.clear()
    headers = auth_headers(make_user())
    ids = [
        _upload(client, headers, f"p{i}.png", _png(color=(i * 40, 30, 30)), "image/png").json()[
            "id"
        ]
        for i in range(3)
    ]
    _upload(client, headers, "broken.jpg", b"not an image at all", "image/jpeg")
    _upload(client, headers, "notes.txt", b"text", "text/plain")

    staged = []
    real = file_service.prepare_download
    monkeypatch.setattr(
        file_service, "prepare_download", lambda *a, **k: staged.append(1) or real(*a, **k)
    )

    assert thumbnail_service.pregenerate(db_session, limit=2) == 2  # a few at a time
    assert (
        thumbnail_service.pregenerate(db_session, limit=10) == 1
    )  # the rest; the broken one is skipped
    assert thumbnail_service.pregenerate(db_session, limit=10) == 0  # nothing left, nothing retried
    assert staged == []  # every original was read in place, never copied out first

    token = _media_token(client, headers)
    for file_id in ids:
        response = client.get(f"/api/media/{token}/{file_id}/thumbnail")
        assert response.status_code == 200 and response.content[:2] == b"\xff\xd8"
    assert staged == []  # and they were already cached when asked for
    thumbnail_service._settled.clear()


def test_a_missing_local_object_falls_back_to_the_engine_copy(
    client: TestClient, make_user, auth_headers, monkeypatch
):
    from app.services import file_service
    from app.services.storage_service import StorageService

    headers = auth_headers(make_user())
    file_id = _upload(client, headers, "a.png", _png(), "image/png").json()["id"]
    monkeypatch.setattr(StorageService, "local_path", lambda self, content_hash: None)
    copied = []
    real = file_service.prepare_download
    monkeypatch.setattr(
        file_service, "prepare_download", lambda *a, **k: copied.append(1) or real(*a, **k)
    )
    token = _media_token(client, headers)
    assert client.get(f"/api/media/{token}/{file_id}/thumbnail").status_code == 200
    assert copied == [1]
