import socket

import pytest
from sqlalchemy.exc import IntegrityError

from app.ingestion import IngestionError, detect_chapters, normalize, public_destination
from app.models import BookProject
from app.schemas import ProjectInput
from app.storage import Storage


def test_ingestion_encoding_boundaries_and_contents():
    raw = (
        "CONTENTS\nCHAPTER I\nCHAPTER II\n\nCHAPTER I\n"
        + "A knight arrives. " * 20
        + "\nCHAPTER II\n"
        + "Rebecca treats the wounded knight. " * 20
    ).encode()
    text = normalize(raw)
    chapters = detect_chapters(text)
    assert len(chapters) == 2
    assert "knight arrives" in text[chapters[0]["start_offset"] : chapters[0]["end_offset"]]
    assert chapters[1]["end_offset"] == len(text)
    assert "café" in normalize(("At the café, a story begins. " * 5).encode("cp1252"))


def test_html_and_inferred_chapters():
    text = normalize(
        b"<html><nav>menu</nav><main><h1>Story</h1><p>A long enough story to import here.</p></main></html>",
        "text/html",
    )
    assert "menu" not in text
    assert detect_chapters(text)[0]["start_offset"] == 0
    long_text = ("A paragraph of narrative. " * 100 + "\n\n") * 25
    assert len(detect_chapters(long_text)) > 1


def test_prose_with_heading_prefixes_is_not_a_chapter():
    text = (
        "actors or artists who venture to change their efforts,\n"
        + "A preface paragraph. " * 30
        + "\nbook, has formed a particular idea of the story,\n"
        + "More preface. " * 20
        + "\nCHAPTER I\n"
        + "Ivanhoe arrives. " * 20
        + "\nCHAPTER II\n"
        + "Rebecca acts bravely. " * 20
    )
    chapters = detect_chapters(text)
    assert [c["title"] for c in chapters] == ["Opening", "CHAPTER I", "CHAPTER II"]


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://user:pass@host/",
        "http://127.0.0.1",
        "http://[::1]",
        "http://169.254.169.254",
        "http://10.0.0.1",
        "http://example.com:8080",
    ],
)
def test_ssrf(url):
    with pytest.raises(IngestionError):
        public_destination(url)


def test_dns_rebinding_mixed_address_rejected(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [(2, 1, 6, "", ("8.8.8.8", 80)), (2, 1, 6, "", ("127.0.0.1", 80))],
    )
    with pytest.raises(IngestionError):
        public_destination("http://example.org")


def test_storage_and_rights():
    store = Storage()
    key = store.put("project", b"manuscript", "txt", "text/plain")
    assert store.get(key) == b"manuscript"
    for bad in ["../session-key", "/etc/passwd", "project/../../secret"]:
        with pytest.raises(ValueError):
            store.get(bad)
    with pytest.raises(ValueError):
        ProjectInput(title="Ivanhoe", author="Scott", rights_declaration="Public domain")


def test_database_ownership_foreign_keys(db):
    db.add(
        BookProject(
            user_id="missing",
            title="Book",
            author="Author",
            rights_confirmed=True,
            rights_declaration="I own all rights",
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
