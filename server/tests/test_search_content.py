"""Search inside files (Phase 14): text, PDFs, Word files, safety and the background indexer."""

import io
import zipfile

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models.file_text import FileText
from app.services import index_service, text_extract


def _upload(client, headers, name, data, mime="text/plain", folder_id=None):
    form = {"folder_id": folder_id} if folder_id else {}
    response = client.post(
        "/api/files/upload", files={"file": (name, data, mime)}, data=form, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def _index(db_session):
    return index_service.index_pending(db_session, 100)


def _search(client, headers, q):
    response = client.get("/api/search", params={"q": q}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _make_pdf(text: str) -> bytes:
    """A one-page PDF with a correct cross-reference table."""
    nl = bytes([10])
    stream = f"BT /F1 18 Tf 20 100 Td ({text}) Tj ET".encode()
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 200]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length "
        + str(len(stream)).encode()
        + b">>"
        + nl
        + b"stream"
        + nl
        + stream
        + nl
        + b"endstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out = b"%PDF-1.4" + nl
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += str(number).encode() + b" 0 obj" + nl + body + nl + b"endobj" + nl
    xref = len(out)
    out += b"xref" + nl + b"0 " + str(len(objects) + 1).encode() + nl
    out += b"0000000000 65535 f " + nl
    for offset in offsets:
        out += str(offset).zfill(10).encode() + b" 00000 n " + nl
    out += b"trailer<</Root 1 0 R/Size " + str(len(objects) + 1).encode() + b">>" + nl
    out += b"startxref" + nl + str(xref).encode() + nl + b"%%EOF" + nl
    return out


PDF = _make_pdf("Quasar invoice total")


def _docx(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "word/document.xml",
            f"<w:document><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>",
        )
    return buffer.getvalue()


def test_text_inside_a_file_is_found_with_a_snippet(
    client: TestClient, make_user, auth_headers, db_session
) -> None:
    headers = auth_headers(make_user())
    body = "Meeting notes. " * 30 + "The zeppelin budget was approved on Friday. " + "Other. " * 30
    _upload(client, headers, "notes.txt", body.encode())
    assert _search(client, headers, "zeppelin")["content"] == []  # not indexed yet

    assert _index(db_session) == {"ok": 1, "skipped": 0, "failed": 0}
    result = _search(client, headers, "zeppelin")
    assert [hit["file"]["name"] for hit in result["content"]] == ["notes.txt"]
    assert "zeppelin budget was approved" in result["content"][0]["snippet"]
    assert result["files"] == []  # it matched by contents, not by name


def test_a_name_match_is_not_repeated_as_a_content_match(
    client: TestClient, make_user, auth_headers, db_session
) -> None:
    headers = auth_headers(make_user())
    _upload(client, headers, "zeppelin.txt", b"all about zeppelin")
    _index(db_session)
    result = _search(client, headers, "zeppelin")
    assert [f["name"] for f in result["files"]] == ["zeppelin.txt"]
    assert result["content"] == []


def test_pdf_and_word_files_are_searchable(
    client: TestClient, make_user, auth_headers, db_session
) -> None:
    headers = auth_headers(make_user())
    _upload(client, headers, "invoice.pdf", PDF, "application/pdf")
    _upload(
        client,
        headers,
        "plan.docx",
        _docx("Marmalade strategy &amp; rollout"),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    counts = _index(db_session)
    assert counts["ok"] == 2 and counts["failed"] == 0, counts
    assert [h["file"]["name"] for h in _search(client, headers, "quasar")["content"]] == [
        "invoice.pdf"
    ]
    found = _search(client, headers, "marmalade")["content"]
    assert [h["file"]["name"] for h in found] == ["plan.docx"]
    assert "strategy & rollout" in found[0]["snippet"]


def test_photos_binaries_and_damaged_files_do_not_break_indexing(
    client: TestClient, make_user, auth_headers, db_session
) -> None:
    headers = auth_headers(make_user())
    _upload(client, headers, "photo.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 50, "image/jpeg")
    _upload(client, headers, "fake.txt", b"\x00\x01\x02binary" * 50)  # a "text" file that is binary
    _upload(client, headers, "broken.pdf", b"this is not a pdf", "application/pdf")
    _upload(client, headers, "broken.docx", b"not a zip", "application/octet-stream")
    _upload(client, headers, "good.txt", b"findable words")

    counts = _index(db_session)
    assert counts == {"ok": 1, "skipped": 2, "failed": 2}
    assert [h["file"]["name"] for h in _search(client, headers, "findable")["content"]] == [
        "good.txt"
    ]
    assert _index(db_session) == {"ok": 0, "skipped": 0, "failed": 0}  # nothing is retried


def test_a_changed_file_is_reindexed_and_old_words_stop_matching(
    client: TestClient, make_user, auth_headers, db_session
) -> None:
    headers = auth_headers(make_user())
    _upload(client, headers, "doc.txt", b"first version mentions aardvark")
    _index(db_session)
    assert _search(client, headers, "aardvark")["content"]
    _upload(client, headers, "doc.txt", b"second version mentions platypus")
    assert _search(client, headers, "aardvark")["content"] == []  # stale text is never served
    _index(db_session)
    assert _search(client, headers, "platypus")["content"]
    assert _search(client, headers, "aardvark")["content"] == []


def test_trashed_files_and_other_users_files_are_never_returned(
    client: TestClient, make_user, auth_headers, db_session
) -> None:
    alice = auth_headers(make_user())
    bob = auth_headers(make_user("bob", "bob@example.com"))
    mine = _upload(client, alice, "mine.txt", b"secret walrus plans")
    _upload(client, bob, "bobs.txt", b"bob also writes about walrus")
    _index(db_session)

    assert [h["file"]["name"] for h in _search(client, alice, "walrus")["content"]] == ["mine.txt"]
    client.delete(f"/api/files/{mine['id']}", headers=alice)
    assert _search(client, alice, "walrus")["content"] == []


def test_search_treats_wildcards_literally(
    client: TestClient, make_user, auth_headers, db_session
) -> None:
    headers = auth_headers(make_user())
    _upload(client, headers, "a.txt", b"fifty percent")
    _index(db_session)
    assert _search(client, headers, "%")["content"] == []
    assert _search(client, headers, "_")["content"] == []


def test_purging_a_file_removes_its_text(
    client: TestClient, make_user, auth_headers, db_session
) -> None:
    headers = auth_headers(make_user())
    file = _upload(client, headers, "gone.txt", b"ephemeral text")
    _index(db_session)
    assert db_session.execute(select(FileText)).scalars().all()
    client.delete(f"/api/files/{file['id']}", headers=headers)
    assert client.delete(f"/api/trash/{file['id']}", headers=headers).status_code == 204
    db_session.expire_all()
    assert db_session.execute(select(FileText)).scalars().all() == []


def test_kind_detection() -> None:
    assert text_extract.kind_of("a.PDF", None) == "pdf"
    assert text_extract.kind_of("a.docx", None) == "zipxml"
    assert text_extract.kind_of("main.py", "application/octet-stream") == "plain"
    assert text_extract.kind_of("readme", "text/plain") == "plain"
    assert text_extract.kind_of("photo.jpg", "image/jpeg") is None
    assert text_extract.kind_of("movie.mp4", "video/mp4") is None


def test_a_zip_bomb_part_is_skipped_not_expanded(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(text_extract, "MAX_ZIP_PART_BYTES", 1000)
    path = tmp_path / "bomb.docx"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", "<w:t>" + "A" * 100_000 + "</w:t>")
    assert text_extract.extract_zipxml(path, "docx") == ""
