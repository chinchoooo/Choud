import hashlib

from fastapi.testclient import TestClient


def _create_session(
    client: TestClient,
    headers: dict,
    file_name="video.mp4",
    file_size=30,
    chunk_size=10,
    **extra,
):
    data = {k: v for k, v in extra.items() if v is not None}
    return client.post(
        "/api/uploads",
        json={
            "file_name": file_name,
            "file_size": file_size,
            "chunk_size": chunk_size,
            **data,
        },
        headers=headers,
    )


def _send_chunk(client: TestClient, headers: dict, upload_id: str, index: int, content: bytes):
    return client.post(
        f"/api/uploads/{upload_id}/chunks/{index}",
        files={"chunk": (f"chunk-{index}", content, "application/octet-stream")},
        headers=headers,
    )


def _complete(client: TestClient, headers: dict, upload_id: str):
    return client.post(f"/api/uploads/{upload_id}/complete", headers=headers)


def _split(content: bytes, chunk_size: int) -> list[bytes]:
    return [content[i : i + chunk_size] for i in range(0, len(content), chunk_size)]


def test_create_session_returns_expected_chunk_layout(
    client: TestClient, make_user, auth_headers
) -> None:
    user = make_user()
    response = _create_session(client, auth_headers(user), file_size=25, chunk_size=10)

    assert response.status_code == 201
    body = response.json()
    assert body["file_name"] == "video.mp4"
    assert body["chunk_size"] == 10
    assert body["total_chunks"] == 3  # ceil(25 / 10)
    assert body["status"] == "pending"


def test_full_upload_out_of_order_then_complete_matches_original_hash(
    client: TestClient, make_user, auth_headers
) -> None:
    user = make_user()
    headers = auth_headers(user)
    content = bytes(range(256)) * 3  # 768 bytes, not a multiple of chunk_size
    chunks = _split(content, chunk_size=100)

    session = _create_session(
        client, headers, file_size=len(content), chunk_size=100
    ).json()
    upload_id = session["id"]
    assert session["total_chunks"] == len(chunks)

    # Send out of order, on purpose.
    for i in reversed(range(len(chunks))):
        ack = _send_chunk(client, headers, upload_id, i, chunks[i])
        assert ack.status_code == 200, ack.text
        assert ack.json()["index"] == i

    completed = _complete(client, headers, upload_id)
    assert completed.status_code == 200, completed.text
    body = completed.json()
    assert body["size"] == len(content)
    assert body["content_hash"] == hashlib.sha256(content).hexdigest()
    assert body["name"] == "video.mp4"


def test_resuming_after_a_partial_upload_only_needs_the_missing_chunks(
    client: TestClient, make_user, auth_headers
) -> None:
    user = make_user()
    headers = auth_headers(user)
    content = b"resumable upload content spanning several chunks of data!!"
    chunks = _split(content, chunk_size=10)

    session = _create_session(client, headers, file_size=len(content), chunk_size=10).json()
    upload_id = session["id"]

    # "Connection drops" after the first two chunks.
    _send_chunk(client, headers, upload_id, 0, chunks[0])
    _send_chunk(client, headers, upload_id, 1, chunks[1])

    status_response = client.get(f"/api/uploads/{upload_id}", headers=headers)
    assert status_response.status_code == 200
    status_body = status_response.json()
    assert status_body["received_chunk_indices"] == [0, 1]
    assert status_body["missing_chunk_indices"] == list(range(2, len(chunks)))

    # Client resumes, sending only what's missing.
    for i in status_body["missing_chunk_indices"]:
        ack = _send_chunk(client, headers, upload_id, i, chunks[i])
        assert ack.status_code == 200

    completed = _complete(client, headers, upload_id)
    assert completed.status_code == 200
    assert completed.json()["content_hash"] == hashlib.sha256(content).hexdigest()


def test_resending_an_already_received_chunk_does_not_duplicate_it(
    client: TestClient, make_user, auth_headers
) -> None:
    user = make_user()
    headers = auth_headers(user)
    session = _create_session(client, headers, file_size=10, chunk_size=10).json()
    upload_id = session["id"]

    first = _send_chunk(client, headers, upload_id, 0, b"0123456789")
    second = _send_chunk(client, headers, upload_id, 0, b"0123456789")

    assert first.json()["received_count"] == 1
    assert second.json()["received_count"] == 1


def test_complete_with_a_missing_chunk_is_rejected(
    client: TestClient, make_user, auth_headers
) -> None:
    user = make_user()
    headers = auth_headers(user)
    session = _create_session(client, headers, file_size=20, chunk_size=10).json()
    upload_id = session["id"]

    _send_chunk(client, headers, upload_id, 0, b"0123456789")
    # Chunk 1 deliberately never sent.

    response = _complete(client, headers, upload_id)
    assert response.status_code == 409


def test_complete_verifies_against_an_expected_hash_when_provided(
    client: TestClient, make_user, auth_headers
) -> None:
    user = make_user()
    headers = auth_headers(user)
    content = b"content whose hash we will pre-declare"
    session = _create_session(
        client,
        headers,
        file_size=len(content),
        chunk_size=len(content),
        expected_hash=hashlib.sha256(b"a completely different payload").hexdigest(),
    ).json()
    upload_id = session["id"]

    _send_chunk(client, headers, upload_id, 0, content)
    response = _complete(client, headers, upload_id)

    assert response.status_code == 409


def test_chunk_index_out_of_range_is_rejected(
    client: TestClient, make_user, auth_headers
) -> None:
    user = make_user()
    headers = auth_headers(user)
    session = _create_session(client, headers, file_size=10, chunk_size=10).json()
    upload_id = session["id"]

    response = _send_chunk(client, headers, upload_id, 5, b"0123456789")
    assert response.status_code == 422


def test_upload_into_missing_folder_returns_404(
    client: TestClient, make_user, auth_headers
) -> None:
    user = make_user()
    response = _create_session(
        client,
        auth_headers(user),
        folder_id="00000000-0000-0000-0000-000000000000",
    )
    assert response.status_code == 404


def test_upload_session_is_scoped_to_its_owner(
    client: TestClient, make_user, auth_headers
) -> None:
    owner = make_user(username="owner", email="owner@example.com")
    intruder = make_user(username="intruder", email="intruder@example.com")
    session = _create_session(client, auth_headers(owner)).json()

    response = client.get(f"/api/uploads/{session['id']}", headers=auth_headers(intruder))
    assert response.status_code == 404

    chunk_response = _send_chunk(
        client, auth_headers(intruder), session["id"], 0, b"0123456789"
    )
    assert chunk_response.status_code == 404


def test_completed_upload_cannot_be_completed_again(
    client: TestClient, make_user, auth_headers
) -> None:
    user = make_user()
    headers = auth_headers(user)
    content = b"0123456789"
    session = _create_session(
        client, headers, file_size=len(content), chunk_size=len(content)
    ).json()
    upload_id = session["id"]
    _send_chunk(client, headers, upload_id, 0, content)
    first = _complete(client, headers, upload_id)
    assert first.status_code == 200

    second = _complete(client, headers, upload_id)
    assert second.status_code == 409


def test_abandon_deletes_the_session_and_its_chunks(
    client: TestClient, make_user, auth_headers, fake_engine_client
) -> None:
    user = make_user()
    headers = auth_headers(user)
    session = _create_session(client, headers, file_size=10, chunk_size=10).json()
    upload_id = session["id"]
    _send_chunk(client, headers, upload_id, 0, b"0123456789")

    response = client.delete(f"/api/uploads/{upload_id}", headers=headers)
    assert response.status_code == 204

    assert client.get(f"/api/uploads/{upload_id}", headers=headers).status_code == 404
    assert not fake_engine_client._upload_dir(upload_id).exists()


def test_sweep_expired_uploads_removes_only_expired_pending_sessions(
    db_session, make_user
) -> None:
    from datetime import UTC, datetime, timedelta

    from app.models.upload import Upload
    from app.services.upload_service import sweep_expired_uploads

    user = make_user()

    expired = Upload(
        owner_id=user.id,
        file_name="old.bin",
        file_size=10,
        chunk_size=10,
        total_chunks=1,
        status="pending",
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )
    still_valid = Upload(
        owner_id=user.id,
        file_name="new.bin",
        file_size=10,
        chunk_size=10,
        total_chunks=1,
        status="pending",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add_all([expired, still_valid])
    db_session.commit()

    swept = sweep_expired_uploads(db_session)

    assert swept == 1
    remaining_ids = {u.file_name for u in db_session.query(Upload).all()}
    assert remaining_ids == {"new.bin"}
