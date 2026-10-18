"""EXPLICIT OPT-IN ONLY. Makes paid calls. Run from backend after migrating a disposable database."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
if os.environ.get("PAID_SMOKE_TEST") != "1":
    raise SystemExit("Disabled. Set PAID_SMOKE_TEST=1 only when you authorize real API charges.")

from hashlib import sha256
from uuid import uuid4

from app.config import settings
from app.db import SessionLocal
from app.exporter import export_book
from app.models import (
    BookProject,
    ChapterSummary,
    Character,
    GenerationJob,
    Page,
    PageScript,
    SourceDocument,
    User,
)
from app.schemas import ProjectInput
from app.storage import Storage
from app.workflow import Workflow

if settings().ai_mode != "live":
    raise SystemExit("AI_MODE must be live. Configure the server API key and confirm current pricing first.")

# A user-supplied excerpt avoids relying on a particular edition's wording. No paid call occurs before validation.
source_path = os.environ.get("SMOKE_MANUSCRIPT")
if not source_path:
    raise SystemExit(
        "Set SMOKE_MANUSCRIPT to a short public-domain TXT passage featuring exactly two named characters."
    )
from app.ingestion import detect_chapters, normalize

text = normalize(Path(source_path).read_bytes())
if len(text) > 5000 or len(detect_chapters(text)) != 1:
    raise SystemExit("Use one chapter and at most 5,000 characters for the paid smoke test.")
with SessionLocal() as db:
    user = User(email=f"smoke-{uuid4()}@example.org", password_hash="disabled-script-account")
    db.add(user)
    db.flush()
    config = ProjectInput(
        title="Ivanhoe — API smoke proof",
        author="Sir Walter Scott",
        pages_per_chapter=2,
        rights_confirmed=True,
        rights_declaration="Operator confirms public-domain source in target test market.",
        budget_usd=float(os.environ.get("SMOKE_BUDGET_USD", "5")),
    ).model_dump()
    project = BookProject(
        user_id=user.id,
        title=config["title"],
        author=config["author"],
        config=config,
        rights_confirmed=True,
        rights_declaration=config["rights_declaration"],
        budget_usd=config["budget_usd"],
    )
    db.add(project)
    db.flush()
    raw = text.encode()
    key = Storage().put(project.id, raw, "txt", "text/plain")
    db.add(
        SourceDocument(
            project_id=project.id,
            original_author=project.author,
            rights=project.rights_declaration,
            storage_key=key,
            sha256=sha256(raw).hexdigest(),
            char_count=len(text),
        )
    )
    job = GenerationJob(project_id=project.id)
    db.add(job)
    db.commit()
    flow = Workflow(db, job)
    flow.ingest_source()
    flow.detect_chapters()
    flow.summarize_chapters()
    flow.analyze_full_story()
    flow.extract_characters()
    flow.generate_character_bible()
    chars = flow.rows(Character)
    if len(chars) != 2:
        raise SystemExit(
            f"Expected two characters, extracted {len(chars)}. Review the retained project before spending on images."
        )
    for summary in flow.rows(ChapterSummary):
        summary.approved = True
    for character in chars:
        ref = flow.portrait(character)
        character.approved_reference_id = ref.id
        character.locked = True
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
    db.commit()
    result = export_book(db, project)
    print(
        f"Paid smoke complete. Project {project.id}; export {result.id}. Review the proof QA. No automatic publication."
    )
