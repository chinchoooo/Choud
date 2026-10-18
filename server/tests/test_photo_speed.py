"""Fast photo access: WebP thumbnails, stable cacheable URLs, batched thumbnails, placeholders."""

import io
import struct
import uuid

from fastapi.testclient import TestClient
from PIL import Image

from app.models.file import File
from app.services import thumbnail_service


def _png(color=(200, 40, 40), size=(600, 400)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def _upload(client, headers, name, data, mime="image/png") -> dict:
    response = client.post("/api/files/upload", files={"file": (name, data, mime)}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _frames(body: bytes):
    out, pos = [], 0
    while pos < len(body):
        file_id = uuid.UUID(bytes=body[pos : pos + 16])
        status, length = struct.unpack(">BI", body[pos + 16 : pos + 21])
        out.append((file_id, status, body[pos + 21 : pos + 21 + length]))
        pos += 21 + length
    return out


# --- WebP thumbnails ------------------------------------------------------------------------------


def test_webp_thumbnail_is_smaller_and_keeps_the_aspect(
    client: TestClient, make_user, auth_headers
):
    headers = auth_headers(make_user())
    file = _upload(client, headers, "a.png", _png(size=(2000, 1000)))
    response = client.get(f"/api/thumbs/{file['id']}?size=256&format=webp", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"
    image = Image.open(io.BytesIO(response.content))
    assert image.format == "WEBP" and image.size == (256, 128)
    jpeg = client.get(f"/api/thumbs/{file['id']}?size=256&format=jpg", headers=headers)
    assert jpeg.headers["content-type"] == "image/jpeg"


def test_unknown_format_or_size_is_refused(client: TestClient, make_user, auth_headers):
    headers = auth_headers(make_user())
    file = _upload(client, headers, "a.png", _png())
    assert client.get(f"/api/thumbs/{file['id']}?format=gif", headers=headers).status_code == 415
    assert client.get(f"/api/thumbs/{file['id']}?size=7", headers=headers).status_code == 415


# --- stable, cacheable URL ------------------------------------------------------------------------


def test_stable_thumbnail_is_immutable_and_answers_304(client: TestClient, make_user, auth_headers):
    headers = auth_headers(make_user())
    file = _upload(client, headers, "a.png", _png())
    first = client.get(f"/api/thumbs/{file['id']}?v=abc", headers=headers)
    assert first.status_code == 200
    assert "immutable" in first.headers["cache-control"]
    assert "private" in first.headers["cache-control"]
    etag = first.headers["etag"]
    again = client.get(
        f"/api/thumbs/{file['id']}?v=abc", headers={**headers, "If-None-Match": etag}
    )
    assert again.status_code == 304 and again.content == b""


def test_stable_thumbnail_needs_a_login_and_is_private(client: TestClient, make_user, auth_headers):
    alice = auth_headers(make_user())
    bob = auth_headers(make_user("bob", "bob@example.com"))
    file = _upload(client, alice, "a.png", _png())
    assert client.get(f"/api/thumbs/{file['id']}").status_code == 401
    assert client.get(f"/api/thumbs/{file['id']}", headers=bob).status_code == 404


def test_stable_thumbnail_changes_when_the_picture_does(
    client: TestClient, make_user, auth_headers
):
    headers = auth_headers(make_user())
    one = _upload(client, headers, "a.png", _png((200, 0, 0)))
    two = _upload(client, headers, "b.png", _png((0, 0, 200)))
    a = client.get(f"/api/thumbs/{one['id']}", headers=headers)
    b = client.get(f"/api/thumbs/{two['id']}", headers=headers)
    assert a.headers["etag"] != b.headers["etag"]


# --- batch ----------------------------------------------------------------------------------------


def test_batch_returns_every_thumbnail_in_one_response(client: TestClient, make_user, auth_headers):
    headers = auth_headers(make_user())
    ids = [_upload(client, headers, f"p{i}.png", _png((i * 40, 30, 30)))["id"] for i in range(3)]
    note = _upload(client, headers, "n.txt", b"hello", "text/plain")["id"]
    ghost = str(uuid.uuid4())

    response = client.post(
        "/api/media/thumbs",
        json={"ids": [*ids, note, ghost], "size": 256, "format": "webp"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    frames = _frames(response.content)
    assert [str(f[0]) for f in frames] == [*ids, note, ghost]  # same order as asked
    for _, status, payload in frames[:3]:
        assert status == 0 and Image.open(io.BytesIO(payload)).format == "WEBP"
    assert frames[3][1] == 2 and frames[3][2] == b""  # a text file has no thumbnail
    assert frames[4][1] == 2  # unknown id


def test_batch_makes_only_a_few_on_the_spot_and_marks_the_rest_pending(
    client: TestClient, make_user, auth_headers
):
    headers = auth_headers(make_user())
    ids = [_upload(client, headers, f"p{i}.png", _png((i * 20, 30, 30)))["id"] for i in range(7)]
    response = client.post("/api/media/thumbs", json={"ids": ids}, headers=headers)
    statuses = [f[1] for f in _frames(response.content)]
    assert statuses.count(0) == 4 and statuses.count(1) == 3
    # Asking again finds the first four ready, so four more are made.
    again = [
        f[1]
        for f in _frames(
            client.post("/api/media/thumbs", json={"ids": ids}, headers=headers).content
        )
    ]
    assert again.count(0) == 7 - again.count(1) and again.count(0) >= 7 - 3


def test_batch_never_returns_someone_elses_photo(client: TestClient, make_user, auth_headers):
    alice = auth_headers(make_user())
    bob = auth_headers(make_user("bob", "bob@example.com"))
    mine = _upload(client, alice, "a.png", _png())["id"]
    response = client.post("/api/media/thumbs", json={"ids": [mine]}, headers=bob)
    assert [f[1] for f in _frames(response.content)] == [2]


def test_batch_limits_and_validation(client: TestClient, make_user, auth_headers):
    headers = auth_headers(make_user())
    too_many = [str(uuid.uuid4()) for _ in range(49)]
    assert (
        client.post("/api/media/thumbs", json={"ids": too_many}, headers=headers).status_code == 422
    )
    assert client.post("/api/media/thumbs", json={"ids": []}, headers=headers).status_code == 422
    odd = client.post(
        "/api/media/thumbs", json={"ids": [str(uuid.uuid4())], "size": 9}, headers=headers
    )
    assert odd.status_code == 422
    assert client.post("/api/media/thumbs", json={"ids": [str(uuid.uuid4())]}).status_code == 401


# --- placeholders ---------------------------------------------------------------------------------


def test_pregeneration_fills_in_the_thumbhash_and_listings_carry_it(
    client: TestClient, make_user, auth_headers, db_session
):
    thumbnail_service._settled.clear()
    headers = auth_headers(make_user())
    file = _upload(client, headers, "a.png", _png((220, 30, 30)))
    assert client.get(f"/api/files/{file['id']}", headers=headers).json()["thumbhash"] is None

    assert thumbnail_service.pregenerate(db_session, limit=5) == 1
    db_session.expire_all()
    row = db_session.get(File, uuid.UUID(file["id"]))
    assert row.thumbhash and len(row.thumbhash) < 60
    listed = client.get("/api/library/photos?kind=all&offset=0&limit=10", headers=headers).json()
    assert listed["items"][0]["thumbhash"] == row.thumbhash
    assert thumbnail_service.pregenerate(db_session, limit=5) == 0  # done; not redone


# --- library index (the whole timeline as compact rows) -------------------------------------------


def _index(client, headers, **params):
    return client.get("/api/library/index", params=params, headers=headers)


def test_index_lists_every_photo_and_video_compactly(client: TestClient, make_user, auth_headers):
    headers = auth_headers(make_user())
    first = _upload(client, headers, "IMG_1.png", _png())
    _upload(client, headers, "notes.txt", b"text", "text/plain")  # not a photo
    client.put(f"/api/library/favorites/{first['id']}", headers=headers)

    body = _index(client, headers).json()
    assert body["full"] is True and body["removed"] == []
    assert body["columns"][:2] == ["id", "name"]
    assert [row[1] for row in body["rows"]] == ["IMG_1.png"]
    assert body["favorites"] == [first["id"]]
    assert body["cursor"]


def test_index_since_returns_only_what_changed_and_what_was_trashed(
    client: TestClient, make_user, auth_headers, db_session
):
    from datetime import UTC, datetime, timedelta

    headers = auth_headers(make_user())
    old = _upload(client, headers, "old.png", _png((1, 2, 3)))
    # Backdate it: the test must not depend on clock resolution (SQLite keeps whole seconds).
    row = db_session.get(File, uuid.UUID(old["id"]))
    row.updated_at = datetime.now(UTC) - timedelta(hours=1)
    db_session.commit()
    cursor = _index(client, headers).json()["cursor"]

    new = _upload(client, headers, "new.png", _png((9, 9, 9)))
    client.delete(f"/api/files/{old['id']}", headers=headers)

    delta = _index(client, headers, since=cursor).json()
    assert delta["full"] is False
    assert [row[1] for row in delta["rows"]] == ["new.png"]
    assert delta["removed"] == [old["id"]]
    assert new["id"] in [row[0] for row in delta["rows"]]


def test_index_answers_304_when_nothing_changed(client: TestClient, make_user, auth_headers):
    headers = auth_headers(make_user())
    _upload(client, headers, "a.png", _png())
    first = _index(client, headers)
    again = client.get(
        "/api/library/index", headers={**headers, "If-None-Match": first.headers["etag"]}
    )
    assert again.status_code == 304
    _upload(client, headers, "b.png", _png((5, 5, 5)))
    changed = client.get(
        "/api/library/index", headers={**headers, "If-None-Match": first.headers["etag"]}
    )
    assert changed.status_code == 200


def test_index_is_private_and_needs_a_login(client: TestClient, make_user, auth_headers):
    alice = auth_headers(make_user())
    bob = auth_headers(make_user("bob", "bob@example.com"))
    _upload(client, alice, "a.png", _png())
    assert _index(client, bob).json()["rows"] == []
    assert client.get("/api/library/index").status_code == 401
    assert _index(client, alice, since="not-a-date").status_code == 422
