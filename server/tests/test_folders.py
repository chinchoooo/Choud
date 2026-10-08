from fastapi.testclient import TestClient


def test_create_root_folder(client: TestClient, make_user, auth_headers) -> None:
    user = make_user()
    response = client.post(
        "/api/folders", json={"name": "Research"}, headers=auth_headers(user)
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Research"
    assert body["parent_id"] is None
    assert body["owner_id"] == str(user.id)


def test_create_nested_folder(client: TestClient, make_user, auth_headers) -> None:
    user = make_user()
    headers = auth_headers(user)
    parent = client.post("/api/folders", json={"name": "Projects"}, headers=headers).json()

    response = client.post(
        "/api/folders",
        json={"name": "Sub", "parent_id": parent["id"]},
        headers=headers,
    )

    assert response.status_code == 201
    assert response.json()["parent_id"] == parent["id"]


def test_create_folder_with_missing_parent_returns_404(
    client: TestClient, make_user, auth_headers
) -> None:
    user = make_user()
    response = client.post(
        "/api/folders",
        json={"name": "Orphan", "parent_id": "00000000-0000-0000-0000-000000000000"},
        headers=auth_headers(user),
    )

    assert response.status_code == 404


def test_create_folder_rejects_duplicate_name_in_same_parent(
    client: TestClient, make_user, auth_headers
) -> None:
    user = make_user()
    headers = auth_headers(user)
    client.post("/api/folders", json={"name": "Photos"}, headers=headers)

    response = client.post("/api/folders", json={"name": "Photos"}, headers=headers)

    assert response.status_code == 409


def test_get_folder(client: TestClient, make_user, auth_headers) -> None:
    user = make_user()
    headers = auth_headers(user)
    created = client.post("/api/folders", json={"name": "Docs"}, headers=headers).json()

    response = client.get(f"/api/folders/{created['id']}", headers=headers)

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_get_folder_not_found(client: TestClient, make_user, auth_headers) -> None:
    user = make_user()
    response = client.get(
        "/api/folders/00000000-0000-0000-0000-000000000000", headers=auth_headers(user)
    )

    assert response.status_code == 404


def test_folder_endpoints_require_authentication(client: TestClient) -> None:
    assert client.post("/api/folders", json={"name": "X"}).status_code == 401
    assert client.get("/api/folders/00000000-0000-0000-0000-000000000000").status_code == 401


def test_cross_user_cannot_see_another_users_folder(
    client: TestClient, make_user, auth_headers
) -> None:
    owner = make_user(username="owner", email="owner@example.com")
    intruder = make_user(username="intruder", email="intruder@example.com")
    folder = client.post(
        "/api/folders", json={"name": "Private"}, headers=auth_headers(owner)
    ).json()

    response = client.get(f"/api/folders/{folder['id']}", headers=auth_headers(intruder))

    assert response.status_code == 404


def test_rename_folder(client: TestClient, make_user, auth_headers) -> None:
    user = make_user()
    headers = auth_headers(user)
    folder = client.post("/api/folders", json={"name": "Old"}, headers=headers).json()

    response = client.patch(
        f"/api/folders/{folder['id']}", json={"name": "New"}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["name"] == "New"


def test_rename_folder_to_taken_name_returns_409(
    client: TestClient, make_user, auth_headers
) -> None:
    user = make_user()
    headers = auth_headers(user)
    client.post("/api/folders", json={"name": "A"}, headers=headers)
    b = client.post("/api/folders", json={"name": "B"}, headers=headers).json()

    response = client.patch(f"/api/folders/{b['id']}", json={"name": "A"}, headers=headers)

    assert response.status_code == 409


def test_move_folder_to_another_parent(client: TestClient, make_user, auth_headers) -> None:
    user = make_user()
    headers = auth_headers(user)
    a = client.post("/api/folders", json={"name": "A"}, headers=headers).json()
    b = client.post("/api/folders", json={"name": "B"}, headers=headers).json()

    response = client.patch(
        f"/api/folders/{b['id']}", json={"parent_id": a["id"]}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["parent_id"] == a["id"]


def test_move_folder_into_itself_returns_409(
    client: TestClient, make_user, auth_headers
) -> None:
    user = make_user()
    headers = auth_headers(user)
    a = client.post("/api/folders", json={"name": "A"}, headers=headers).json()

    response = client.patch(
        f"/api/folders/{a['id']}", json={"parent_id": a["id"]}, headers=headers
    )

    assert response.status_code == 409


def test_move_folder_into_its_own_descendant_returns_409(
    client: TestClient, make_user, auth_headers
) -> None:
    user = make_user()
    headers = auth_headers(user)
    parent = client.post("/api/folders", json={"name": "Parent"}, headers=headers).json()
    child = client.post(
        "/api/folders", json={"name": "Child", "parent_id": parent["id"]}, headers=headers
    ).json()

    response = client.patch(
        f"/api/folders/{parent['id']}", json={"parent_id": child["id"]}, headers=headers
    )

    assert response.status_code == 409


def test_delete_empty_folder(client: TestClient, make_user, auth_headers) -> None:
    user = make_user()
    headers = auth_headers(user)
    folder = client.post("/api/folders", json={"name": "Empty"}, headers=headers).json()

    response = client.delete(f"/api/folders/{folder['id']}", headers=headers)

    assert response.status_code == 204
    assert client.get(f"/api/folders/{folder['id']}", headers=headers).status_code == 404


def test_delete_folder_with_subfolder_returns_409(
    client: TestClient, make_user, auth_headers
) -> None:
    user = make_user()
    headers = auth_headers(user)
    parent = client.post("/api/folders", json={"name": "Parent"}, headers=headers).json()
    client.post("/api/folders", json={"name": "Child", "parent_id": parent["id"]}, headers=headers)

    response = client.delete(f"/api/folders/{parent['id']}", headers=headers)

    assert response.status_code == 409


def test_delete_folder_with_file_returns_409(
    client: TestClient, make_user, auth_headers
) -> None:
    user = make_user()
    headers = auth_headers(user)
    folder = client.post("/api/folders", json={"name": "HasFile"}, headers=headers).json()
    client.post(
        "/api/files/upload",
        files={"file": ("a.txt", b"hello", "text/plain")},
        data={"folder_id": folder["id"]},
        headers=headers,
    )

    response = client.delete(f"/api/folders/{folder['id']}", headers=headers)

    assert response.status_code == 409


def test_delete_folder_whose_only_file_is_trashed_detaches_that_file(
    client: TestClient, db_session, make_user, auth_headers
) -> None:
    from app.models.file import File

    user = make_user()
    headers = auth_headers(user)
    folder = client.post("/api/folders", json={"name": "Old"}, headers=headers).json()
    uploaded = client.post(
        "/api/files/upload",
        files={"file": ("note.txt", b"keep me", "text/plain")},
        data={"folder_id": folder["id"]},
        headers=headers,
    ).json()
    client.delete(f"/api/files/{uploaded['id']}", headers=headers)

    response = client.delete(f"/api/folders/{folder['id']}", headers=headers)

    assert response.status_code == 204
    trashed = db_session.get(File, uploaded["id"])
    assert trashed is not None  # not destroyed (Rule 5)
    assert trashed.deleted_at is not None
    assert trashed.folder_id is None  # restores to the root
