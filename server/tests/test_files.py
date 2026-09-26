from fastapi.testclient import TestClient


def _upload(
    client: TestClient,
    headers: dict,
    filename="hello.txt",
    content=b"hello world",
    **extra,
):
    data = {k: v for k, v in extra.items() if v is not None}
    return client.post(
        "/api/files/upload",
        files={"file": (filename, content, "text/plain")},
        data=data,
        headers=headers,
    )


def test_upload_file(client: TestClient, make_user, auth_headers) -> None:
    user = make_user()
    response = _upload(client, auth_headers(user))

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "hello.txt"
    assert body["size"] == len(b"hello world")
    assert body["folder_id"] is None
    assert body["owner_id"] == str(user.id)


def test_upload_and_download_round_trip_is_byte_identical(
    client: TestClient, make_user, auth_headers
) -> None:
    user = make_user()
    headers = auth_headers(user)
    content = bytes(range(256)) * 100
    uploaded = _upload(client, headers, filename="data.bin", content=content).json()

    response = client.get(f"/api/files/{uploaded['id']}/download", headers=headers)

    assert response.status_code == 200
    assert response.content == content


def test_download_of_corrupted_object_returns_a_clean_500(
    client: TestClient, make_user, auth_headers, fake_engine_client
) -> None:
    user = make_user()
    headers = auth_headers(user)
    uploaded = _upload(client, headers, content=b"original bytes").json()

    object_path = fake_engine_client._path_for(uploaded["content_hash"])
    object_path.write_bytes(b"these bytes were tampered with")

    response = client.get(f"/api/files/{uploaded['id']}/download", headers=headers)

    assert response.status_code == 500


def test_upload_into_missing_folder_returns_404(
    client: TestClient, make_user, auth_headers
) -> None:
    user = make_user()
    response = _upload(
        client, auth_headers(user), folder_id="00000000-0000-0000-0000-000000000000"
    )

    assert response.status_code == 404


def test_upload_into_folder_owned_by_someone_else_returns_404(
    client: TestClient, make_user, auth_headers
) -> None:
    owner = make_user(username="owner", email="owner@example.com")
    intruder = make_user(username="intruder", email="intruder@example.com")
    folder = client.post(
        "/api/folders", json={"name": "Private"}, headers=auth_headers(owner)
    ).json()

    response = _upload(client, auth_headers(intruder), folder_id=folder["id"])

    assert response.status_code == 404


def test_upload_rejects_path_traversal_filename(
    client: TestClient, make_user, auth_headers
) -> None:
    user = make_user()
    response = _upload(client, auth_headers(user), filename="../../etc/passwd")

    assert response.status_code == 422


def test_upload_rejects_empty_filename(client: TestClient, make_user, auth_headers) -> None:
    user = make_user()
    response = _upload(client, auth_headers(user), filename="")

    assert response.status_code == 422


def test_uploading_identical_content_twice_creates_two_rows_but_one_object(
    client: TestClient, make_user, auth_headers, fake_engine_client
) -> None:
    user = make_user()
    headers = auth_headers(user)
    first = _upload(client, headers, filename="a.txt", content=b"same bytes").json()
    second = _upload(client, headers, filename="b.txt", content=b"same bytes").json()

    assert first["id"] != second["id"]
    assert first["content_hash"] == second["content_hash"]

    # Physical dedup: only one object on "disk" for this hash, even though
    # two rows reference it (docs/storage.md#deduplication).
    object_path = fake_engine_client._path_for(first["content_hash"])
    assert object_path.is_file()
    assert object_path.stat().st_size == len(b"same bytes")


def test_uploading_different_content_creates_distinct_objects(
    client: TestClient, make_user, auth_headers
) -> None:
    user = make_user()
    headers = auth_headers(user)
    first = _upload(client, headers, filename="a.txt", content=b"content A").json()
    second = _upload(client, headers, filename="b.txt", content=b"content B").json()

    assert first["content_hash"] != second["content_hash"]


def test_get_file_metadata(client: TestClient, make_user, auth_headers) -> None:
    user = make_user()
    headers = auth_headers(user)
    uploaded = _upload(client, headers).json()

    response = client.get(f"/api/files/{uploaded['id']}", headers=headers)

    assert response.status_code == 200
    assert response.json()["id"] == uploaded["id"]


def test_cross_user_cannot_access_file(client: TestClient, make_user, auth_headers) -> None:
    owner = make_user(username="owner", email="owner@example.com")
    intruder = make_user(username="intruder", email="intruder@example.com")
    uploaded = _upload(client, auth_headers(owner)).json()

    get_resp = client.get(f"/api/files/{uploaded['id']}", headers=auth_headers(intruder))
    download_resp = client.get(
        f"/api/files/{uploaded['id']}/download", headers=auth_headers(intruder)
    )
    delete_resp = client.delete(f"/api/files/{uploaded['id']}", headers=auth_headers(intruder))

    assert get_resp.status_code == 404
    assert download_resp.status_code == 404
    assert delete_resp.status_code == 404


def test_rename_file(client: TestClient, make_user, auth_headers) -> None:
    user = make_user()
    headers = auth_headers(user)
    uploaded = _upload(client, headers).json()

    response = client.patch(
        f"/api/files/{uploaded['id']}", json={"name": "renamed.txt"}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["name"] == "renamed.txt"


def test_move_file_to_a_folder_and_back_to_root(
    client: TestClient, make_user, auth_headers
) -> None:
    user = make_user()
    headers = auth_headers(user)
    folder = client.post("/api/folders", json={"name": "Docs"}, headers=headers).json()
    uploaded = _upload(client, headers).json()

    moved = client.patch(
        f"/api/files/{uploaded['id']}", json={"folder_id": folder["id"]}, headers=headers
    )
    assert moved.status_code == 200
    assert moved.json()["folder_id"] == folder["id"]

    moved_back = client.patch(
        f"/api/files/{uploaded['id']}", json={"folder_id": None}, headers=headers
    )
    assert moved_back.status_code == 200
    assert moved_back.json()["folder_id"] is None


def test_move_file_to_missing_folder_returns_404(
    client: TestClient, make_user, auth_headers
) -> None:
    user = make_user()
    headers = auth_headers(user)
    uploaded = _upload(client, headers).json()

    response = client.patch(
        f"/api/files/{uploaded['id']}",
        json={"folder_id": "00000000-0000-0000-0000-000000000000"},
        headers=headers,
    )

    assert response.status_code == 404


def test_delete_is_soft_and_hides_file_from_listing_and_download(
    client: TestClient, make_user, auth_headers
) -> None:
    user = make_user()
    headers = auth_headers(user)
    uploaded = _upload(client, headers).json()

    delete_resp = client.delete(f"/api/files/{uploaded['id']}", headers=headers)
    assert delete_resp.status_code == 204

    assert client.get(f"/api/files/{uploaded['id']}", headers=headers).status_code == 404
    assert (
        client.get(f"/api/files/{uploaded['id']}/download", headers=headers).status_code == 404
    )

    listing = client.get("/api/files", headers=headers).json()
    assert uploaded["id"] not in [f["id"] for f in listing["files"]]


def test_delete_is_idempotent_returns_404_when_already_deleted(
    client: TestClient, make_user, auth_headers
) -> None:
    user = make_user()
    headers = auth_headers(user)
    uploaded = _upload(client, headers).json()
    client.delete(f"/api/files/{uploaded['id']}", headers=headers)

    response = client.delete(f"/api/files/{uploaded['id']}", headers=headers)

    assert response.status_code == 404


def test_list_directory_root(client: TestClient, make_user, auth_headers) -> None:
    user = make_user()
    headers = auth_headers(user)
    client.post("/api/folders", json={"name": "Projects"}, headers=headers)
    _upload(client, headers, filename="readme.txt")

    response = client.get("/api/files", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["folder"] is None
    assert [f["name"] for f in body["subfolders"]] == ["Projects"]
    assert [f["name"] for f in body["files"]] == ["readme.txt"]


def test_list_directory_for_missing_folder_returns_404(
    client: TestClient, make_user, auth_headers
) -> None:
    user = make_user()
    response = client.get(
        "/api/files?folder_id=00000000-0000-0000-0000-000000000000",
        headers=auth_headers(user),
    )

    assert response.status_code == 404


def test_search_finds_files_and_folders_by_partial_name(
    client: TestClient, make_user, auth_headers
) -> None:
    user = make_user()
    headers = auth_headers(user)
    client.post("/api/folders", json={"name": "Research Notes"}, headers=headers)
    _upload(client, headers, filename="research-paper.pdf")
    _upload(client, headers, filename="unrelated.txt")

    response = client.get("/api/search", params={"q": "research"}, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert [f["name"] for f in body["folders"]] == ["Research Notes"]
    assert [f["name"] for f in body["files"]] == ["research-paper.pdf"]


def test_search_is_scoped_to_the_current_user(client: TestClient, make_user, auth_headers) -> None:
    owner = make_user(username="owner", email="owner@example.com")
    other = make_user(username="other", email="other@example.com")
    _upload(client, auth_headers(owner), filename="secret-plan.txt")

    response = client.get("/api/search", params={"q": "secret"}, headers=auth_headers(other))

    assert response.status_code == 200
    assert response.json()["files"] == []


def test_file_endpoints_require_authentication(client: TestClient) -> None:
    assert client.get("/api/files").status_code == 401
    assert client.get("/api/search", params={"q": "x"}).status_code == 401
