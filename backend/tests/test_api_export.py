import io
import zipfile

import fitz
import pytest
from fastapi.testclient import TestClient

from app.exporter import export_book, spine_width
from app.main import app, windows
from app.models import (
    Character,
    Page,
    PageScript,
)
from app.schemas import PrintSettings
from app.worker import execute
from app.workflow import Workflow
from tests.helpers import PASSAGE, make_project


@pytest.fixture
def client():
    windows.clear()
    with TestClient(app) as client:
        yield client


def sign_up(client, email="publisher@example.org"):
    response = client.post("/auth/register", json={"email": email, "password": "a-secure-test-password"})
    assert response.status_code == 201, response.text


def test_auth_ownership_origins_and_limits(client):
    assert client.get("/projects").status_code == 401
    sign_up(client)
    payload = dict(
        title="Ivanhoe", author="Scott", rights_confirmed=True, rights_declaration="Public domain in the US"
    )
    response = client.post("/projects", json=payload, headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    project = client.post("/projects", json=payload).json()
    client.post("/auth/logout")
    sign_up(client, "other@example.org")
    assert client.get("/projects/" + project["id"]).status_code == 404
    assert client.get(f"/projects/{project['id']}/assets/{project['id']}/secret.png").status_code == 404
    response = client.post("/projects", json={**payload, "rights_confirmed": False})
    assert response.status_code == 422
    assert (
        client.post(
            "/auth/login", json={"email": "other@example.org", "password": "wrong-password"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/auth/login", json={"email": "other@example.org", "password": "a-secure-test-password"}
        ).status_code
        == 200
    )
    for _ in range(16):
        response = client.post(
            "/auth/login", json={"email": "other@example.org", "password": "wrong-password"}
        )
    assert response.status_code == 429


def test_full_api_acceptance_flow_and_restart_persistence(client, db):
    sign_up(client)
    response = client.post(
        "/projects",
        json=dict(
            title="Ivanhoe",
            author="Sir Walter Scott",
            pages_per_chapter=2,
            rights_confirmed=True,
            rights_declaration="Public domain in the United States",
        ),
    )
    assert response.status_code == 201, response.text
    project = response.json()
    root = f"/projects/{project['id']}"
    response = client.post(
        root + "/source/upload", files={"file": ("manuscript.txt", PASSAGE.encode(), "text/plain")}
    )
    assert response.status_code == 200, response.text
    assert (
        client.post(
            root + "/source/upload", files={"file": ("again.txt", PASSAGE.encode(), "text/plain")}
        ).status_code
        == 409
    )
    job = client.post(root + "/run").json()
    execute(job["id"])
    book = client.get(root).json()
    assert len(book["chapters"]) == 1
    for summary in book["summaries"]:
        result = client.put(
            root + f"/summaries/{summary['id']}", json={"data": summary["data"], "approved": True}
        )
        assert result.status_code == 200, result.text
    result = client.post(
        root + f"/jobs/{job['id']}/control", json={"action": "resume", "approve_batch": True}
    )
    assert result.status_code == 200, result.text
    execute(job["id"])
    book = client.get(root).json()
    assert {"Ivanhoe", "Rowena", "Rebecca"}.issubset({c["name"] for c in book["characters"]})
    for character in book["characters"]:
        ref = next(r for r in book["references"] if r["character_id"] == character["id"])
        assert (
            client.post(
                root + f"/characters/{character['id']}/approve", json={"reference_id": ref["id"]}
            ).status_code
            == 200
        )
    client.post(root + f"/jobs/{job['id']}/control", json={"action": "resume"})
    execute(job["id"])
    book = client.get(root).json()
    assert len(book["pages"]) == 2
    for page in book["pages"]:
        script = next(s for s in book["scripts"] if s["page_id"] == page["id"])
        result = client.put(
            root + f"/pages/{page['id']}",
            json={
                "script": script["data"],
                "script_approved": True,
                "layout": page["layout"],
                "elements": [],
            },
        )
        assert result.status_code == 200, result.text
    client.post(root + f"/jobs/{job['id']}/control", json={"action": "resume", "approve_batch": True})
    execute(job["id"])
    book = client.get(root).json()
    assert book["metrics"]["pages_generated"] == 2
    page = book["pages"][0]
    canonical = [c["approved_reference_id"] for c in book["characters"]]
    regen = client.post(root + f"/pages/{page['id']}/generate").json()
    execute(regen["id"])
    book = client.get(root).json()
    assert [c["approved_reference_id"] for c in book["characters"]] == canonical
    assert len(book["artworks"]) == 3
    coverjob = client.post(root + "/cover/generate").json()
    execute(coverjob["id"])
    book = client.get(root).json()
    assert (
        client.put(
            root + "/cover",
            json={
                "title": "IVANHOE",
                "author": "Sir Walter Scott",
                "artwork_approved": True,
                "back_text": "A tale of honor and courage.",
            },
        ).status_code
        == 200
    )
    for page in book["pages"]:
        script = next(s for s in book["scripts"] if s["page_id"] == page["id"])
        elements = [{"kind": e["kind"], **e["data"]} for e in book["elements"] if e["page_id"] == page["id"]]
        result = client.put(
            root + f"/pages/{page['id']}",
            json={
                "script": script["data"],
                "script_approved": True,
                "approved": True,
                "layout": page["layout"],
                "elements": elements,
            },
        )
        assert result.status_code == 200, result.text
    result = client.post(root + "/exports")
    assert result.status_code == 200, result.text
    exported = result.json()
    manifest = exported["manifest"]
    assert manifest["page_count"] == 6
    assert manifest["qa"]["interior"]["embedded_fonts"]
    assert manifest["qa"]["cover"]["embedded_fonts"]
    assert not manifest["qa"]["publication_ready"]
    package = client.get(root + "/assets/" + exported["zip_key"])
    assert package.status_code == 200
    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        assert set(archive.namelist()) == {"interior.pdf", "cover.pdf", "qa-report.json", "manifest.json"}
        with fitz.open(stream=archive.read("interior.pdf"), filetype="pdf") as pdf:
            assert len(pdf) == 6
            assert pdf[0].rect.width == 432 and pdf[0].rect.height == 648
            assert "Ivanhoe" in pdf[0].get_text()
    # A new API client and new SQLAlchemy session see retained canonical designs, progress and exports.
    client.post("/auth/logout")
    assert (
        client.post(
            "/auth/login", json={"email": "publisher@example.org", "password": "a-secure-test-password"}
        ).status_code
        == 200
    )
    restored = client.get(root).json()
    assert restored["exports"][0]["id"] == exported["id"]
    assert [c["approved_reference_id"] for c in restored["characters"]] == canonical
    assert len(restored["artworks"]) == 3
    assert client.delete(root + f"/pages/{restored['pages'][0]['id']}").status_code == 200
    after_delete = client.get(root).json()
    assert len(after_delete["pages"]) == 1 and after_delete["pages"][0]["position"] == 0
    assert client.delete(root + f"/pages/{after_delete['pages'][0]['id']}").status_code == 200
    added = client.post(root + "/pages", json={"chapter_id": restored["chapters"][0]["id"]})
    assert added.status_code == 200 and added.json()["position"] == 0


def test_pdf_bleed_resolution_fonts_and_cover_spine(db):
    project, job = make_project(db)
    flow = Workflow(db, job)
    flow.detect_chapters()
    flow.summarize_chapters()
    flow.analyze_full_story()
    flow.extract_characters()
    for c in flow.rows(Character):
        ref = flow.portrait(c)
        c.approved_reference_id = ref.id
        c.locked = True
    db.commit()
    flow.plan_pages()
    flow.generate_page_scripts()
    for script in flow.rows(PageScript):
        script.approved = True
    db.commit()
    for page in flow.rows(Page):
        flow.page_art(page)
        flow.compose_page(page)
        page.approved = True
    flow.cover_art()
    project.config = {**project.config, "print": PrintSettings(bleed=True, paper="cream").model_dump()}
    db.commit()
    result = export_book(db, project)
    qa = result.manifest["qa"]
    assert qa["interior"]["dimensions_correct"] and qa["interior"]["embedded_fonts"]
    assert result.manifest["interior_points"] == [441, 666]
    assert result.manifest["spine_inches"] == spine_width(6, "cream")
    assert any("DPI" in w for w in qa["warnings"])
    assert any("OFFLINE" in w for w in qa["warnings"])
    assert result.manifest["cover_points"] == [(12 + spine_width(6, "cream") + 0.25) * 72, 666]


def test_edit_layout_outside_page_is_rejected(client, db):
    sign_up(client)
    from app.schemas import LayoutElementInput

    with pytest.raises(ValueError):
        LayoutElementInput(kind="speech", text="outside", x=0.9, y=0.9, width=0.5, height=0.2)


def test_manual_art_upload_visual_qa_font_and_style_persistence(client, db):
    from PIL import Image
    from sqlalchemy import func, select

    from app.auth import token
    from app.models import PageArtwork, StylePreset

    project, job = make_project(db)
    job.status = "review"
    db.commit()
    client.cookies.set("alexandria_session", token(project.user_id))
    flow = Workflow(db, job)
    flow.detect_chapters()
    flow.summarize_chapters()
    flow.extract_characters()
    for character in flow.rows(Character):
        reference = flow.portrait(character)
        character.approved_reference_id = reference.id
        character.locked = True
    db.commit()
    flow.plan_pages()
    flow.generate_page_scripts()
    page = flow.rows(Page)[0]
    image = io.BytesIO()
    Image.new("RGB", (1800, 2700), "#405640").save(image, "PNG")
    root = f"/projects/{project.id}"
    result = client.post(
        root + f"/pages/{page.id}/upload", files={"file": ("print-art.png", image.getvalue(), "image/png")}
    )
    assert result.status_code == 200, result.text
    artwork = result.json()
    assert artwork["metadata_json"]["source"] == "manual upload"
    assert not artwork["metadata_json"]["offline"]
    qa_job = client.post(root + f"/pages/{page.id}/qa").json()
    execute(qa_job["id"])
    db.expire_all()
    assert db.get(PageArtwork, artwork["id"]).metadata_json["qa_reference_ids"]
    assert db.scalar(select(func.count()).select_from(StylePreset)) == 8
    font = client.get("/font")
    assert font.status_code == 200 and font.headers["content-type"] == "font/ttf"
    assert len(font.content) > 10000
    result = client.post(
        root + "/style/references", files={"file": ("style.png", image.getvalue(), "image/png")}
    )
    assert result.status_code == 200, result.text
    db.expire_all()
    style_inputs = Workflow(db, job).style_references()
    assert len(style_inputs) == 1 and style_inputs[0][0].startswith("style:")
    assert style_inputs[0][1] == image.getvalue()
    assert all(c.locked for c in flow.rows(Character))


def test_novel_length_contents_paginate_without_losing_chapters():
    from types import SimpleNamespace

    from app.exporter import contents_plan

    chapters = [
        SimpleNamespace(id=str(i), title=f"CHAPTER {i + 1} — A new turn in the story") for i in range(100)
    ]
    pages = [SimpleNamespace(chapter_id=str(i)) for i in range(100)]
    groups = contents_plan(chapters, pages, 432, 648, 36)
    assert len(groups) > 1
    entries = [entry for group in groups for entry, _ in group]
    assert len(entries) == 100
    assert entries[0].endswith(str(3 + len(groups)))
    assert entries[-1].endswith(str(102 + len(groups)))
    assert all(sum(height for _, height in group) <= 648 - 72 - 48 for group in groups)
