"""Repairing the dates of photos that were uploaded without one."""

import io
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.models.file import File
from app.services import dates_service


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("IMG_20250206_160717396.jpg", datetime(2025, 2, 6, 16, 7, 17, tzinfo=UTC)),
        ("PXL_20241231_235959123.jpg", datetime(2024, 12, 31, 23, 59, 59, tzinfo=UTC)),
        ("VID_20250101_000001.mp4", datetime(2025, 1, 1, 0, 0, 1, tzinfo=UTC)),
        ("Screenshot_20250206-160717.png", datetime(2025, 2, 6, 16, 7, 17, tzinfo=UTC)),
        ("Screenshot_2025-02-06-16-07-17-123.png", datetime(2025, 2, 6, 16, 7, 17, tzinfo=UTC)),
        ("IMG-20250206-WA0007.jpg", datetime(2025, 2, 6, 0, 0, 0, tzinfo=UTC)),
        ("signal-2025-02-06-160717.jpg", datetime(2025, 2, 6, 16, 7, 17, tzinfo=UTC)),
        ("2025-02-06 16.07.17.jpg", datetime(2025, 2, 6, 16, 7, 17, tzinfo=UTC)),
        ("20250206_160717.jpg", datetime(2025, 2, 6, 16, 7, 17, tzinfo=UTC)),
    ],
)
def test_dates_are_read_from_common_file_names(name, expected) -> None:
    assert dates_service.date_from_name(name) == expected


@pytest.mark.parametrize(
    "name",
    [
        "holiday.jpg",
        "IMG_99999999_000000.jpg",
        "IMG_20251340_100000.jpg",
        "IMG_18000101_000000.jpg",
        "x.png",
    ],
)
def test_names_without_a_believable_date_give_none(name) -> None:
    assert dates_service.date_from_name(name) is None


def _jpeg(with_exif: str | None) -> bytes:
    image = Image.new("RGB", (40, 30), (10, 120, 200))
    buffer = io.BytesIO()
    if with_exif:
        exif = Image.Exif()
        exif[0x8769] = {36867: with_exif}
        image.save(buffer, "JPEG", exif=exif)
    else:
        image.save(buffer, "JPEG")
    return buffer.getvalue()


def _upload(client, headers, name, data, mime="image/jpeg", **form):
    response = client.post(
        "/api/files/upload", files={"file": (name, data, mime)}, data=form, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_exif_dates_are_read(tmp_path) -> None:
    path = tmp_path / "p.jpg"
    path.write_bytes(_jpeg("2023:07:04 12:30:45"))
    assert dates_service.date_from_exif(path) == datetime(2023, 7, 4, 12, 30, 45, tzinfo=UTC)
    plain = tmp_path / "plain.jpg"
    plain.write_bytes(_jpeg(None))
    assert dates_service.date_from_exif(plain) is None
    assert dates_service.date_from_exif(tmp_path / "missing.jpg") is None


def test_preview_then_apply_fixes_only_undated_photos(
    client: TestClient, make_user, auth_headers, db_session
) -> None:
    headers = auth_headers(make_user())
    by_name = _upload(client, headers, "IMG_20250206_160717396.jpg", _jpeg(None))
    by_exif = _upload(client, headers, "holiday.jpg", _jpeg("2022:12:25 09:00:00"))
    hopeless = _upload(client, headers, "mystery.jpg", _jpeg(None))
    already = _upload(
        client, headers, "IMG_20200101_000000.jpg", _jpeg(None), taken_at="2019-05-05T10:00:00Z"
    )
    note = _upload(client, headers, "notes.txt", b"hello", "text/plain")

    preview = client.post("/api/library/fix-dates", json={}, headers=headers).json()
    assert preview["dry_run"] is True
    assert (preview["checked"], preview["from_name"], preview["from_exif"]) == (3, 1, 1)
    assert preview["no_date_found"] == 1 and preview["fixed"] == 2
    assert any("IMG_20250206_160717396.jpg -> 2025-02-06 (name)" in e for e in preview["examples"])
    db_session.expire_all()
    assert db_session.get(File, by_name["id"]).taken_at is None  # a preview changes nothing

    done = client.post("/api/library/fix-dates", json={"dry_run": False}, headers=headers).json()
    assert done["fixed"] == 2
    db_session.expire_all()
    assert db_session.get(File, by_name["id"]).taken_at.date().isoformat() == "2025-02-06"
    assert db_session.get(File, by_exif["id"]).taken_at.date().isoformat() == "2022-12-25"
    assert db_session.get(File, hopeless["id"]).taken_at is None
    assert (
        db_session.get(File, already["id"]).taken_at.date().isoformat() == "2019-05-05"
    )  # untouched
    assert db_session.get(File, note["id"]).taken_at is None

    # They now sort by their real dates on the timeline.
    photos = client.get("/api/library/photos?kind=all&offset=0&limit=10", headers=headers).json()
    dates = [(p["name"], (p["taken_at"] or "")[:10]) for p in photos["items"]]
    assert ("IMG_20250206_160717396.jpg", "2025-02-06") in dates

    again = client.post("/api/library/fix-dates", json={"dry_run": False}, headers=headers).json()
    assert again["fixed"] == 0  # nothing left to fix; safe to run twice


def test_fixing_dates_needs_a_login_and_is_private(
    client: TestClient, make_user, auth_headers, db_session
) -> None:
    alice = auth_headers(make_user())
    bob = auth_headers(make_user("bob", "bob@example.com"))
    mine = _upload(client, alice, "IMG_20250206_160717.jpg", _jpeg(None))
    assert client.post("/api/library/fix-dates", json={}).status_code == 401
    other = client.post("/api/library/fix-dates", json={"dry_run": False}, headers=bob).json()
    assert other["checked"] == 0
    db_session.expire_all()
    assert db_session.get(File, mine["id"]).taken_at is None  # Bob's run did not touch Alice's file
