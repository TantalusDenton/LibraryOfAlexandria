import base64
import io
from types import SimpleNamespace

import pytest
from PIL import Image
from sqlalchemy import func, select

from app.ai import AI, BudgetExceeded, UncertainCall, reserve
from app.config import settings
from app.models import (
    ChapterSummary,
    Character,
    CharacterReference,
    GenerationArtifact,
    Page,
    PageArtwork,
    PageScript,
    UsageRecord,
    WorkflowCheckpoint,
)
from app.schemas import Summary
from app.worker import execute
from app.workflow import ReviewRequired, Workflow
from tests.helpers import make_project


def test_structured_summary_is_validated_and_cached(db):
    project, job = make_project(db)
    ai = AI(db, project)
    result = ai.structured(Summary, "Analyze", {"text": "Ivanhoe sees Rebecca. Rowena arrives."}, "summary")
    assert "Ivanhoe" in result.characters
    assert result.events
    count = db.scalar(select(func.count()).select_from(GenerationArtifact))
    assert (
        ai.structured(Summary, "Analyze", {"text": "Ivanhoe sees Rebecca. Rowena arrives."}, "summary")
        == result
    )
    assert db.scalar(select(func.count()).select_from(GenerationArtifact)) == count


def test_budget_and_uncertain_call(db):
    project, _ = make_project(db)
    reserve(db, project, "first", "model", "image", 9)
    with pytest.raises(BudgetExceeded):
        reserve(db, project, "second", "model", "image", 2)
    with pytest.raises(UncertainCall):
        reserve(db, project, "first", "model", "image", 0.5)
    assert db.scalar(select(func.count()).select_from(UsageRecord)) == 1


def test_graph_review_resume_and_canonical_lock(db):
    project, job = make_project(db)
    execute(job.id)
    db.expire_all()
    db.refresh(job)
    assert job.status == "review"
    assert job.stage == "generate_character_references"
    chars = list(db.scalars(select(Character)))
    assert {"Ivanhoe", "Rowena", "Rebecca"}.issubset({c.name for c in chars})
    checkpoint_count = db.scalar(select(func.count()).select_from(WorkflowCheckpoint))
    for summary in db.scalars(select(ChapterSummary)):
        summary.approved = True
    project.config = {**project.config, "batch_approvals": {"generate_character_references": True}}
    job.status = "queued"
    db.commit()
    execute(job.id)
    db.expire_all()
    db.refresh(job)
    assert job.status == "review" and job.stage == "plan_pages"
    refs = list(db.scalars(select(CharacterReference)))
    assert len(refs) == len(chars)
    for char in db.scalars(select(Character)):
        ref = next(r for r in refs if r.character_id == char.id)
        char.approved_reference_id = ref.id
        char.locked = True
    job.status = "queued"
    db.commit()
    execute(job.id)
    db.expire_all()
    db.refresh(job)
    assert job.status == "review" and job.stage == "generate_page_art"
    assert len(list(db.scalars(select(Page)))) == 2
    for script in db.scalars(select(PageScript)):
        script.approved = True
    project = db.get(type(project), project.id)
    project.config = {
        **project.config,
        "batch_approvals": {**project.config["batch_approvals"], "generate_page_art": True},
    }
    job.status = "queued"
    db.commit()
    execute(job.id)
    db.expire_all()
    db.refresh(job)
    assert job.status == "review" and job.stage == "export_pdf"
    assert db.scalar(select(func.count()).select_from(PageArtwork)) == 2
    canonical = {c.id: c.approved_reference_id for c in db.scalars(select(Character))}
    page = db.scalar(select(Page))
    flow = Workflow(db, job)
    flow.page_art(page)
    assert {c.id: c.approved_reference_id for c in db.scalars(select(Character))} == canonical
    with pytest.raises(ReviewRequired):
        flow.portrait(db.scalar(select(Character)), force=True)
    assert db.scalar(select(func.count()).select_from(WorkflowCheckpoint)) > checkpoint_count


def test_cancellation_before_chargeable_work(db):
    project, job = make_project(db)
    job.control = "cancel"
    db.commit()
    execute(job.id)
    db.refresh(job)
    assert job.status == "cancelled"
    assert db.scalar(select(func.count()).select_from(UsageRecord)) == 0


def test_actual_reference_bytes_route_to_edit_with_limits(db, monkeypatch):
    project, _ = make_project(db)
    cfg = settings()
    monkeypatch.setattr(cfg, "ai_mode", "live")
    monkeypatch.setattr(cfg, "openai_api_key", "test-key")
    monkeypatch.setattr(cfg, "pricing_confirmed", True)
    monkeypatch.setattr(cfg, "max_image_references", 1)
    output = io.BytesIO()
    Image.new("RGB", (10, 10)).save(output, "PNG")
    raw = output.getvalue()
    seen = {}

    def edit(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(raw).decode())])

    client = SimpleNamespace(
        images=SimpleNamespace(edit=edit, generate=lambda **kw: pytest.fail("Must use edits"))
    )
    payload, metadata = AI(db, project, client=client).image(
        "Scene", [("canonical-v1", raw), ("secondary-v1", raw)], "page"
    )
    assert seen["image"][0][1] == raw
    assert payload == raw
    assert metadata["reference_ids"] == ["canonical-v1"]
    assert metadata["omitted_reference_ids"] == ["secondary-v1"]


def test_rate_limit_retry_is_bounded_and_does_not_double_reserve(db, monkeypatch):
    import httpx
    from openai import RateLimitError

    project, _ = make_project(db)
    cfg = settings()
    monkeypatch.setattr(cfg, "ai_mode", "live")
    monkeypatch.setattr(cfg, "openai_api_key", "test-key")
    monkeypatch.setattr(cfg, "pricing_confirmed", True)
    ai = AI(db, project, client=SimpleNamespace())
    attempts = []

    def call():
        attempts.append(1)
        if len(attempts) == 1:
            raise RateLimitError(
                "limit",
                response=httpx.Response(429, request=httpx.Request("POST", "https://api.openai.com")),
                body={},
            )
        return "ok"

    result, usage = ai._paid("retry", "test", "text", 0.01, call)
    assert result == "ok" and len(attempts) == 2
    assert db.scalar(select(func.count()).select_from(UsageRecord)) == 1
