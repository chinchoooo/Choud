"""Size limits on uploads: nothing can bypass the quota or exhaust memory with one huge request."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.services import file_service, thumbnail_service, upload_service


def _session(client, headers, size, chunk, **extra):
    return client.post(
        "/api/uploads",
        json={"file_name": "f.bin", "file_size": size, "chunk_size": chunk, **extra},
        headers=headers,
    )


def _chunk(client, headers, upload_id, index, data):
    return client.post(
        f"/api/uploads/{upload_id}/chunks/{index}",
        files={"chunk": ("chunk", data, "application/octet-stream")},
        headers=headers,
    )


def test_a_chunk_bigger_than_the_session_promised_is_refused(
    client: TestClient, make_user, auth_headers
):
    """Declare a tiny file to pass the quota check, then try to push a big chunk: refused."""
    headers = auth_headers(make_user())
    session = _session(client, headers, size=10, chunk=10).json()
    response = _chunk(client, headers, session["id"], 0, b"x" * 5000)
    assert response.status_code == 422
    assert "exactly 10 bytes" in response.json()["detail"]


def test_a_short_chunk_is_refused_too(client: TestClient, make_user, auth_headers):
    headers = auth_headers(make_user())
    session = _session(client, headers, size=25, chunk=10).json()
    assert _chunk(client, headers, session["id"], 0, b"x" * 9).status_code == 422
    assert _chunk(client, headers, session["id"], 0, b"x" * 10).status_code == 200


def test_the_last_chunk_must_be_exactly_the_remainder(client: TestClient, make_user, auth_headers):
    headers = auth_headers(make_user())
    session = _session(client, headers, size=25, chunk=10).json()
    assert _chunk(client, headers, session["id"], 2, b"x" * 10).status_code == 422  # too long
    assert _chunk(client, headers, session["id"], 2, b"x" * 5).status_code == 200


def test_chunk_size_and_chunk_count_are_bounded(client: TestClient, make_user, auth_headers):
    headers = auth_headers(make_user())
    too_big = upload_service.MAX_CHUNK_BYTES + 1
    assert _session(client, headers, size=too_big, chunk=too_big).status_code == 422
    # one-byte chunks of a big file would mean billions of chunk rows
    assert _session(client, headers, size=upload_service.MAX_CHUNKS + 1, chunk=1).status_code == 422
    assert _session(client, headers, size=upload_service.MAX_CHUNKS, chunk=1).status_code == 201


def test_single_request_upload_has_a_ceiling(
    client: TestClient, make_user, auth_headers, monkeypatch
):
    monkeypatch.setattr(file_service, "MAX_SIMPLE_UPLOAD_BYTES", 1000)
    headers = auth_headers(make_user())
    ok = client.post(
        "/api/files/upload", files={"file": ("a.bin", b"x" * 1000, "text/plain")}, headers=headers
    )
    assert ok.status_code == 201
    big = client.post(
        "/api/files/upload", files={"file": ("b.bin", b"x" * 1001, "text/plain")}, headers=headers
    )
    assert big.status_code == 413
    assert "chunked" in big.json()["detail"]


def test_video_thumbnails_only_run_ffmpeg_on_real_containers(tmp_path: Path):
    mp4 = tmp_path / "a.mp4"
    mp4.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    webm = tmp_path / "a.webm"
    webm.write_bytes(b"\x1a\x45\xdf\xa3" + b"\x00" * 20)
    playlist = tmp_path / "evil.mp4"
    playlist.write_bytes(b"#EXTM3U\n#EXT-X-VERSION:3\nhttp://169.254.169.254/latest/meta-data\n")
    concat = tmp_path / "concat.mp4"
    concat.write_bytes(b"ffconcat version 1.0\nfile '/etc/passwd'\n")

    assert thumbnail_service.sniff_container(mp4) == "mov"
    assert thumbnail_service.sniff_container(webm) == "matroska"
    assert thumbnail_service.sniff_container(playlist) is None
    assert thumbnail_service.sniff_container(concat) is None
    assert thumbnail_service.sniff_container(tmp_path / "missing") is None


def test_a_fake_video_that_is_really_a_playlist_gets_no_thumbnail(
    client: TestClient, make_user, auth_headers
):
    headers = auth_headers(make_user())
    playlist = b"#EXTM3U\n#EXT-X-VERSION:3\nhttp://169.254.169.254/latest/meta-data\n"
    file_id = client.post(
        "/api/files/upload", files={"file": ("clip.mp4", playlist, "video/mp4")}, headers=headers
    ).json()["id"]
    token = client.post("/api/media/token", headers=headers).json()["token"]
    response = client.get(f"/api/media/{token}/{file_id}/thumbnail")
    assert response.status_code == 415
