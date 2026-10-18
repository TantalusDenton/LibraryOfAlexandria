import io
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.ai import AI, UncertainCall
from app.config import settings
from app.models import Character, GenerationArtifact, PageLayoutElement, PageScript, UsageRecord
from app.schemas import Summary
from app.storage import Storage
from app.workflow import Workflow
from tests.helpers import make_project


def test_all_llm_schemas_follow_openai_strict_object_contract():
    from openai.lib._pydantic import to_strict_json_schema

    from app.schemas import CharacterDesign, CharacterList, Plan, Script, StoryAnalysis, Summary, VisualQA

    def check(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
                assert set(node.get("required", [])) == set(node.get("properties", {}))
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for value in node:
                check(value)

    for schema in (Summary, StoryAnalysis, CharacterList, CharacterDesign, Plan, Script, VisualQA):
        check(to_strict_json_schema(schema))


def test_reference_generation_cannot_silently_fall_back_to_text_only(db, monkeypatch):
    project, _ = make_project(db)
    monkeypatch.setattr(settings(), "max_reference_bytes", 1)
    with pytest.raises(ValueError, match="No reference image fits"):
        AI(db, project).image("Page with canonical character", [("approved-v1", b"image bytes")], "test")


def test_retry_after_visual_qa_failure_reuses_completed_artwork(db, monkeypatch):
    from app.models import GenerationJob, Page, PageArtwork
    from app.worker import execute

    project, setup_job = make_project(db)
    flow = Workflow(db, setup_job)
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
    for script in flow.rows(PageScript):
        script.approved = True
    page = flow.rows(Page)[0]
    job = GenerationJob(project_id=project.id, kind="page_art", target_id=page.id)
    db.add(job)
    db.commit()
    with monkeypatch.context() as patch:

        def unavailable(*args, **kwargs):
            raise ValueError("Visual QA temporarily unavailable")

        patch.setattr(AI, "visual_qa", unavailable)
        execute(job.id)
    db.expire_all()
    db.refresh(job)
    assert job.status == "failed"
    assert db.scalar(select(func.count()).select_from(PageArtwork)) == 1
    artwork_id = db.get(Page, page.id).current_artwork_id
    job.status = "queued"
    db.commit()
    execute(job.id)
    db.expire_all()
    db.refresh(job)
    assert job.status == "completed"
    assert db.get(Page, page.id).current_artwork_id == artwork_id
    assert db.scalar(select(func.count()).select_from(PageArtwork)) == 1


def test_structured_sdk_response_and_token_accounting(db, monkeypatch):
    project, _ = make_project(db)
    cfg = settings()
    monkeypatch.setattr(cfg, "ai_mode", "live")
    monkeypatch.setattr(cfg, "openai_api_key", "test-key")
    monkeypatch.setattr(cfg, "pricing_confirmed", True)
    parsed = Summary(summary="A faithful summary", characters=["Ivanhoe"], events=[])
    seen = {}

    def parse(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            output_parsed=parsed, usage=SimpleNamespace(input_tokens=120, output_tokens=40)
        )

    client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    result = AI(db, project, client=client).structured(
        Summary, "Summarize", {"text": "A manuscript passage"}, "test"
    )
    assert result == parsed and seen["text_format"] is Summary
    usage = db.scalar(select(UsageRecord))
    assert usage.status == "completed" and usage.input_tokens == 120 and usage.output_tokens == 40
    assert usage.cost_usd == pytest.approx(
        (120 * cfg.input_usd_per_million + 40 * cfg.output_usd_per_million) / 1_000_000
    )


def test_timeout_is_not_silently_retried_or_refunded(db, monkeypatch):
    project, _ = make_project(db)
    cfg = settings()
    monkeypatch.setattr(cfg, "ai_mode", "live")
    monkeypatch.setattr(cfg, "openai_api_key", "test-key")
    monkeypatch.setattr(cfg, "pricing_confirmed", True)
    ai = AI(db, project, client=SimpleNamespace())
    calls = []

    def timeout():
        calls.append(1)
        raise TimeoutError("uncertain provider outcome")

    with pytest.raises(TimeoutError):
        ai._paid("uncertain", "model", "image", 1, timeout)
    assert len(calls) == 1 and db.scalar(select(UsageRecord)).status == "reserved"
    with pytest.raises(UncertainCall):
        ai._paid("uncertain", "model", "image", 1, lambda: "do not run")


def test_s3_interface_keeps_the_same_safe_object_contract(monkeypatch):
    objects = {}

    class S3:
        def put_object(self, **kw):
            assert kw["Bucket"] == "test-bucket"
            objects[kw["Key"]] = kw["Body"]

        def get_object(self, **kw):
            return {"Body": io.BytesIO(objects[kw["Key"]])}

    import boto3

    monkeypatch.setattr(settings(), "storage_backend", "s3")
    monkeypatch.setattr(settings(), "s3_bucket", "test-bucket")
    monkeypatch.setattr(boto3, "client", lambda *a, **kw: S3())
    store = Storage()
    key = store.put("book", b"source", "txt", "text/plain")
    assert store.get(key) == b"source"
    with pytest.raises(ValueError):
        store.get("../secret")


def test_graphic_pages_have_separate_editable_panels_and_text(db):
    project, job = make_project(db, book_type="graphic")
    flow = Workflow(db, job)
    flow.detect_chapters()
    flow.summarize_chapters()
    flow.extract_characters()
    for char in flow.rows(Character):
        ref = flow.portrait(char)
        char.approved_reference_id = ref.id
        char.locked = True
    db.commit()
    flow.plan_pages()
    flow.generate_page_scripts()
    flow.compose_pages()
    assert all(len(s.data["panels"]) >= 2 for s in flow.rows(PageScript))
    assert db.scalar(select(func.count()).select_from(PageLayoutElement)) >= 2


def test_hierarchical_analysis_retains_chunk_event_ledger(db):
    from app.models import ChapterSummary, SourceDocument

    project, job = make_project(db)
    text = (
        "CHAPTER I\n" + ("Ivanhoe travels north. Rebecca accompanies him. " * 350) + "\nA decisive ending. "
    )
    source = db.scalar(select(SourceDocument))
    source.storage_key = Storage().put(project.id, text.encode(), "txt", "text/plain")
    db.commit()
    flow = Workflow(db, job)
    flow.detect_chapters()
    flow.summarize_chapters()
    summary = flow.rows(ChapterSummary)[0]
    chunk_artifacts = [
        a for a in flow.rows(GenerationArtifact) if a.stage == "ai" and "source_start" in a.prompt
    ]
    assert len(chunk_artifacts) > 1
    assert len(summary.data["events"]) == sum(len(a.data["events"]) for a in chunk_artifacts)
