import asyncio
import hashlib
import io
import json
import logging
import mimetypes
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models as m
from .auth import current_user, owned, password_hasher, token
from .config import settings
from .db import SessionLocal, get_db
from .exporter import export_book
from .ingestion import download, normalize
from .schemas import (
    CharacterDesign,
    Credentials,
    LayoutElementInput,
    PrintSettings,
    ProjectInput,
    Script,
    Summary,
)
from .storage import Storage
from .styles import IVANHOE_STYLE, STYLES, style_data
from .worker import enqueue

logger = logging.getLogger("alexandria.api")


def serialize(record):
    return {
        col.name: (value.isoformat() if hasattr(value, "isoformat") else value)
        for col in record.__table__.columns
        if (value := getattr(record, col.name)) is not None
    }


def records(db, cls, project_id):
    return list(db.scalars(select(cls).filter_by(project_id=project_id).order_by(cls.created_at)))


def idle(db, project_id):
    if db.scalar(
        select(m.GenerationJob.id).where(
            m.GenerationJob.project_id == project_id, m.GenerationJob.status.in_(["queued", "running"])
        )
    ):
        raise HTTPException(409, "Pause the active job and wait for it to stop before editing")


def item(db, cls, item_id, project_id):
    value = db.get(cls, item_id)
    if not value or value.project_id != project_id:
        raise HTTPException(404, "Item not found")
    return value


def invalidate(db, project, stages):
    db.execute(
        delete(m.WorkflowCheckpoint).where(
            m.WorkflowCheckpoint.project_id == project.id, m.WorkflowCheckpoint.stage.in_(stages)
        )
    )
    project.config = {**project.config, "batch_approvals": {}}


def start_job(db, project, kind="workflow", target_id=None):
    idle(db, project.id)
    job = m.GenerationJob(project_id=project.id, kind=kind, target_id=target_id)
    db.add(job)
    db.commit()
    try:
        enqueue(job.id)
    except Exception:
        # Database is authoritative: worker supervisor redelivers after Redis is restored.
        logger.warning("queue_dispatch_deferred", extra={"job_id": job.id})
    return serialize(job)


@asynccontextmanager
async def lifespan(app):
    logging.basicConfig(level=settings().log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    with SessionLocal() as db:
        for name in STYLES:
            if not db.scalar(select(m.StylePreset).where(m.StylePreset.name == name)):
                db.add(m.StylePreset(name=name, data=style_data(name)))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()  # Another API replica seeded the same immutable preset names.
    yield


app = FastAPI(title="Library of Alexandria", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings().allowed_origins.split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)
windows = defaultdict(deque)


@app.middleware("http")
async def protection(request, call_next):
    origin = request.headers.get("origin")
    if (
        request.method not in ("GET", "HEAD", "OPTIONS")
        and origin
        and origin not in settings().allowed_origins.split(",")
    ):
        return Response("Origin not allowed", 403)
    if int(request.headers.get("content-length", "0")) > settings().max_upload_bytes + 65536:
        return Response("Upload exceeds size limit", 413)
    if request.url.path != "/health" and not request.url.path.endswith("/events"):
        identity = request.client.host if request.client else "unknown"
        window = "auth" if "/auth/" in request.url.path and request.method == "POST" else "api"
        limit = 15 if window == "auth" else 300
        key = f"alexandria:rate:{identity}:{window}:{int(time.time()) // 60}"
        if settings().redis_url:
            try:
                from redis import Redis

                redis = Redis.from_url(settings().redis_url)
                count = redis.incr(key)
                redis.expire(key, 65)
                if count > limit:
                    return Response("Rate limit exceeded", 429, headers={"Retry-After": "60"})
            except Exception:
                return Response("Rate limiter unavailable", 503)
        else:
            bucket = windows[(identity, window)]
            while bucket and bucket[0] < time.monotonic() - 60:
                bucket.popleft()
            if len(bucket) >= limit:
                return Response("Rate limit exceeded", 429, headers={"Retry-After": "60"})
            bucket.append(time.monotonic())
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(ValueError)
async def bad_value(request, exc):
    return Response(json.dumps({"detail": str(exc)[:500]}), status_code=400, media_type="application/json")


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(select(m.User.id).limit(1))
    return {
        "status": "ok",
        "ai_mode": settings().ai_mode,
        "queue": "azure-storage" if settings().azure_queue_url else (
            "redis" if settings().redis_url else "local-database"
        ),
    }


@app.post("/auth/register", status_code=201)
def register(body: Credentials, response: Response, db: Session = Depends(get_db)):
    if not settings().registration_enabled:
        raise HTTPException(403, "Public registration is disabled")
    user = m.User(email=body.email.lower(), password_hash=password_hasher.hash(body.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Email already registered")
    response.set_cookie(
        "alexandria_session",
        token(user.id),
        httponly=True,
        secure=settings().secure_cookies,
        samesite="strict",
        max_age=604800,
        path="/",
    )
    return {"id": user.id, "email": user.email}


@app.post("/auth/login")
def login(body: Credentials, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(m.User).where(m.User.email == body.email.lower()))
    dummy = (
        "$argon2id$v=19$m=65536,t=3,p=4$YWxleGFuZHJpYXRlc3QxMg$kKXStajWwZGi2VjNIIp5o7sqA37DLyr+zPX1o0fI3eo"
    )
    try:
        valid = password_hasher.verify(body.password, user.password_hash if user else dummy)
    except Exception:
        valid = False
    if not user or not valid:
        raise HTTPException(401, "Email or password incorrect")
    response.set_cookie(
        "alexandria_session",
        token(user.id),
        httponly=True,
        secure=settings().secure_cookies,
        samesite="strict",
        max_age=604800,
        path="/",
    )
    return {"id": user.id, "email": user.email}


@app.post("/auth/logout")
def logout(response: Response):
    response.delete_cookie("alexandria_session", path="/")
    return {"ok": True}


@app.get("/auth/me")
def me(user=Depends(current_user)):
    return {"id": user.id, "email": user.email}


@app.get("/settings")
def system_settings(user=Depends(current_user)):
    cfg = settings()
    return {
        "ai_mode": cfg.ai_mode,
        "text_model": cfg.text_model,
        "image_model": cfg.image_model,
        "economy_image_model": cfg.economy_image_model,
        "pricing_confirmed": cfg.pricing_confirmed,
        "api_key_configured": bool(cfg.openai_api_key),
        "preview_image_ceiling": cfg.preview_image_reservation_usd,
        "final_image_ceiling": cfg.final_image_reservation_usd,
        "storage": cfg.storage_backend,
        "queue": "azure-storage" if cfg.azure_queue_url else ("redis" if cfg.redis_url else "local-database"),
    }


@app.get("/presets")
def presets():
    return {
        "styles": [{"name": name, **style_data(name)} for name in STYLES],
        "ivanhoe": {
            "title": "Ivanhoe",
            "author": "Sir Walter Scott",
            "art_description": IVANHOE_STYLE,
            "source_url": "https://www.gutenberg.org/ebooks/82.txt.utf-8",
        },
    }


def metrics(db, project):
    pages = records(db, m.Page, project.id)
    chars = records(db, m.Character, project.id)
    usage = records(db, m.UsageRecord, project.id)
    exports = records(db, m.Export, project.id)
    chapters = records(db, m.Chapter, project.id)
    return {
        "chapters": len(chapters),
        "chapters_completed": sum(
            all(p.current_artwork_id for p in pages if p.chapter_id == c.id)
            and any(p.chapter_id == c.id for p in pages)
            for c in chapters
        ),
        "pages": len(pages),
        "pages_generated": sum(bool(p.current_artwork_id) for p in pages),
        "characters": len(chars),
        "references_approved": sum(bool(c.locked and c.approved_reference_id) for c in chars),
        "spent_and_reserved_usd": round(sum(u.cost_usd for u in usage), 6),
        "estimated_remaining_image_usd": round(
            (len(pages) - sum(bool(p.current_artwork_id) for p in pages))
            * (
                settings().preview_image_reservation_usd
                if project.config.get("quality") == "low"
                else settings().final_image_reservation_usd
            ),
            2,
        ),
        "qa_status": "passed"
        if exports and exports[-1].manifest["qa"]["publication_ready"]
        else "review required",
    }


@app.get("/projects")
def projects(db: Session = Depends(get_db), user=Depends(current_user)):
    return [
        {**serialize(p), "metrics": metrics(db, p)}
        for p in db.scalars(
            select(m.BookProject)
            .where(m.BookProject.user_id == user.id)
            .order_by(m.BookProject.created_at.desc())
        )
    ]


@app.post("/projects", status_code=201)
def create_project(body: ProjectInput, db: Session = Depends(get_db), user=Depends(current_user)):
    project = m.BookProject(
        user_id=user.id,
        title=body.title,
        author=body.author,
        rights_confirmed=body.rights_confirmed,
        rights_declaration=body.rights_declaration,
        budget_usd=body.budget_usd,
        config=body.model_dump(),
        cover={"title": body.title, "author": body.author},
    )
    db.add(project)
    db.commit()
    return serialize(project)


@app.get("/projects/{project_id}")
def project_detail(project_id: str, db: Session = Depends(get_db), user=Depends(current_user)):
    project = owned(db, project_id, user.id)
    result = {**serialize(project), "metrics": metrics(db, project)}
    for name, cls in [
        ("sources", m.SourceDocument),
        ("chapters", m.Chapter),
        ("summaries", m.ChapterSummary),
        ("characters", m.Character),
        ("references", m.CharacterReference),
        ("pages", m.Page),
        ("scripts", m.PageScript),
        ("artworks", m.PageArtwork),
        ("elements", m.PageLayoutElement),
        ("panels", m.PagePanel),
        ("jobs", m.GenerationJob),
        ("exports", m.Export),
        ("usage", m.UsageRecord),
        ("quality_reports", m.QualityReport),
        ("locations", m.Location),
    ]:
        result[name] = [serialize(x) for x in records(db, cls, project_id)]
    result["analysis"] = [
        serialize(x)
        for x in records(db, m.GenerationArtifact, project_id)
        if x.stage in ("story", "plan", "visual_qa")
    ]
    return result


class BudgetUpdate(BaseModel):
    budget_usd: float = Field(gt=0, le=10000)


@app.patch("/projects/{project_id}/budget")
def change_budget(
    project_id: str, body: BudgetUpdate, db: Session = Depends(get_db), user=Depends(current_user)
):
    project = owned(db, project_id, user.id)
    idle(db, project_id)
    if body.budget_usd < metrics(db, project)["spent_and_reserved_usd"]:
        raise HTTPException(400, "Cap cannot be below already spent/reserved cost")
    project.budget_usd = body.budget_usd
    db.commit()
    return serialize(project)


def save_source(db, project, raw, mime, url=None):
    idle(db, project.id)
    if records(db, m.SourceDocument, project.id):
        raise HTTPException(409, "This book already has a manuscript. Create a new book for another edition.")
    text = normalize(raw, mime)
    payload = text.encode()
    key = Storage().put(project.id, payload, "txt", "text/plain")
    source = m.SourceDocument(
        project_id=project.id,
        source_url=url,
        original_author=project.author,
        edition=project.config["edition"],
        rights=project.rights_declaration,
        storage_key=key,
        sha256=hashlib.sha256(payload).hexdigest(),
        char_count=len(text),
    )
    db.add(source)
    db.commit()
    return serialize(source)


@app.post("/projects/{project_id}/source/upload")
def upload_source(
    project_id: str, file: UploadFile = File(...), db: Session = Depends(get_db), user=Depends(current_user)
):
    project = owned(db, project_id, user.id)
    if (
        not file.filename
        or not file.filename.lower().endswith(".txt")
        or file.content_type not in ("text/plain", "application/octet-stream")
    ):
        raise HTTPException(400, "Upload a .txt manuscript")
    return save_source(db, project, file.file.read(settings().max_upload_bytes + 1), "text/plain")


class URLInput(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


@app.post("/projects/{project_id}/source/url")
def import_url(project_id: str, body: URLInput, db: Session = Depends(get_db), user=Depends(current_user)):
    project = owned(db, project_id, user.id)
    idle(db, project_id)
    try:
        raw, mime = download(body.url)
    except (OSError, TimeoutError) as exc:
        raise HTTPException(502, "Source unavailable. Check network access or upload a TXT file.") from exc
    return save_source(db, project, raw, mime, body.url)


@app.get("/projects/{project_id}/source/text")
def source_text(
    project_id: str,
    start: int = 0,
    end: int = 10000,
    db: Session = Depends(get_db),
    user=Depends(current_user),
):
    owned(db, project_id, user.id)
    source = records(db, m.SourceDocument, project_id)
    if not source:
        raise HTTPException(404, "No manuscript")
    if start < 0 or end <= start or end - start > 20000:
        raise HTTPException(400, "Request at most 20,000 source characters")
    return {"text": Storage().get(source[0].storage_key).decode()[start:end], "start": start, "end": end}


@app.post("/projects/{project_id}/run")
def run(project_id: str, db: Session = Depends(get_db), user=Depends(current_user)):
    project = owned(db, project_id, user.id)
    if not records(db, m.SourceDocument, project_id):
        raise HTTPException(400, "Import a manuscript first")
    return start_job(db, project)


class SummaryEdit(BaseModel):
    data: Summary
    approved: bool = False


@app.put("/projects/{project_id}/summaries/{summary_id}")
def edit_summary(
    project_id: str,
    summary_id: str,
    body: SummaryEdit,
    db: Session = Depends(get_db),
    user=Depends(current_user),
):
    project = owned(db, project_id, user.id)
    idle(db, project_id)
    summary = item(db, m.ChapterSummary, summary_id, project_id)
    changed = summary.data != body.data.model_dump()
    if changed and records(db, m.Page, project_id):
        raise HTTPException(409, "Pages are already planned. Edit their scripts to refine this adaptation.")
    if changed:
        db.add(
            m.GenerationArtifact(
                project_id=project_id,
                stage="summary_revision",
                artifact_key=summary.id,
                version=summary.version,
                data=summary.data,
            )
        )
        summary.data = body.data.model_dump()
        summary.version += 1
        invalidate(db, project, ["analyze_full_story", "extract_characters", "generate_character_bible"])
        db.execute(
            delete(m.GenerationArtifact).where(
                m.GenerationArtifact.project_id == project_id, m.GenerationArtifact.stage == "story"
            )
        )
    summary.approved = body.approved
    db.commit()
    return serialize(summary)


class CharacterEdit(BaseModel):
    data: CharacterDesign


@app.put("/projects/{project_id}/characters/{character_id}")
def edit_character(
    project_id: str,
    character_id: str,
    body: CharacterEdit,
    db: Session = Depends(get_db),
    user=Depends(current_user),
):
    owned(db, project_id, user.id)
    idle(db, project_id)
    char = item(db, m.Character, character_id, project_id)
    if char.locked:
        raise HTTPException(409, "Unlock the canonical design before editing")
    version = (
        len(
            [
                a
                for a in records(db, m.GenerationArtifact, project_id)
                if a.stage == "character_revision" and a.artifact_key == char.id
            ]
        )
        + 1
    )
    db.add(
        m.GenerationArtifact(
            project_id=project_id,
            stage="character_revision",
            artifact_key=char.id,
            version=version,
            data=char.data,
        )
    )
    char.data = body.data.model_dump()
    char.name = body.data.name
    db.commit()
    return serialize(char)


@app.post("/projects/{project_id}/characters/{character_id}/generate")
def generate_reference(
    project_id: str, character_id: str, db: Session = Depends(get_db), user=Depends(current_user)
):
    project = owned(db, project_id, user.id)
    char = item(db, m.Character, character_id, project_id)
    if char.locked:
        raise HTTPException(409, "Unlock this character before regenerating a reference")
    return start_job(db, project, "portrait", char.id)


def image_payload(file):
    raw = file.file.read(settings().max_upload_bytes + 1)
    if len(raw) > settings().max_upload_bytes:
        raise HTTPException(413, "Image too large")
    try:
        image = Image.open(io.BytesIO(raw))
        if image.width * image.height > 24_000_000 or min(image.size) < 64:
            raise ValueError("Reference must be 64px minimum and at most 24 megapixels")
        image = ImageOps.exif_transpose(image).convert("RGB")
        output = io.BytesIO()
        image.save(output, "PNG")
        payload = output.getvalue()
        if len(payload) > settings().max_upload_bytes:
            raise ValueError("Normalized image exceeds the 10 MiB limit")
        return payload
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError):
        raise HTTPException(400, "Upload a valid PNG, JPEG or WebP image")


@app.post("/projects/{project_id}/characters/{character_id}/upload")
def upload_reference(
    project_id: str,
    character_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user=Depends(current_user),
):
    owned(db, project_id, user.id)
    idle(db, project_id)
    char = item(db, m.Character, character_id, project_id)
    if char.locked:
        raise HTTPException(409, "Unlock the character before uploading a new reference")
    version = (
        max(
            [r.version for r in records(db, m.CharacterReference, project_id) if r.character_id == char.id],
            default=0,
        )
        + 1
    )
    key = Storage().put(project_id, image_payload(file), "png", "image/png")
    ref = m.CharacterReference(
        project_id=project_id,
        character_id=char.id,
        storage_key=key,
        version=version,
        metadata_json={"source": "manual upload", "offline": False},
    )
    db.add(ref)
    db.commit()
    return serialize(ref)


class ReferenceApproval(BaseModel):
    reference_id: str


@app.post("/projects/{project_id}/characters/{character_id}/approve")
def approve_reference(
    project_id: str,
    character_id: str,
    body: ReferenceApproval,
    db: Session = Depends(get_db),
    user=Depends(current_user),
):
    owned(db, project_id, user.id)
    idle(db, project_id)
    char = item(db, m.Character, character_id, project_id)
    ref = item(db, m.CharacterReference, body.reference_id, project_id)
    if ref.character_id != char.id:
        raise HTTPException(400, "Reference belongs to another character")
    if char.locked and char.approved_reference_id != ref.id:
        raise HTTPException(409, "Unlock the character before changing its canonical reference")
    char.approved_reference_id = ref.id
    char.locked = True
    db.commit()
    return serialize(char)


@app.post("/projects/{project_id}/characters/{character_id}/unlock")
def unlock(project_id: str, character_id: str, db: Session = Depends(get_db), user=Depends(current_user)):
    project = owned(db, project_id, user.id)
    idle(db, project_id)
    char = item(db, m.Character, character_id, project_id)
    char.locked = False
    for page in records(db, m.Page, project_id):
        page.approved = False
    invalidate(db, project, ["plan_pages", "generate_page_art", "quality_assurance", "export_pdf"])
    db.commit()
    return serialize(char)


class PageEdit(BaseModel):
    script: Script
    script_approved: bool = False
    approved: bool = False
    layout: str = Field(pattern="^(illustrated|panels|full_bleed)$")
    elements: list[LayoutElementInput] = Field(default_factory=list, max_length=30)


@app.put("/projects/{project_id}/pages/{page_id}")
def edit_page(
    project_id: str, page_id: str, body: PageEdit, db: Session = Depends(get_db), user=Depends(current_user)
):
    project = owned(db, project_id, user.id)
    idle(db, project_id)
    page = item(db, m.Page, page_id, project_id)
    script = db.scalar(select(m.PageScript).where(m.PageScript.page_id == page.id))
    chapter = db.get(m.Chapter, page.chapter_id)
    if any(
        p.start < chapter.start_offset or p.end > chapter.end_offset or p.end <= p.start
        for p in body.script.source_passages
    ):
        raise HTTPException(400, "Source passage is outside its chapter")
    changed = script.data != body.script.model_dump() or page.layout != body.layout
    if changed:
        db.add(
            m.GenerationArtifact(
                project_id=project_id,
                stage="script_revision",
                artifact_key=script.id,
                version=script.version,
                data=script.data,
            )
        )
        script.version += 1
    script.data = body.script.model_dump()
    script.approved = body.script_approved
    if body.approved and (not page.current_artwork_id or not script.approved):
        raise HTTPException(400, "Approve a script and generate art before approving the page")
    page.layout = body.layout
    page.approved = body.approved and not changed
    db.execute(delete(m.PageLayoutElement).where(m.PageLayoutElement.page_id == page.id))
    for element in body.elements:
        db.add(
            m.PageLayoutElement(
                project_id=project_id,
                page_id=page.id,
                kind=element.kind,
                data=element.model_dump(exclude={"kind"}),
            )
        )
    db.execute(delete(m.PagePanel).where(m.PagePanel.page_id == page.id))
    for i, panel in enumerate(body.script.panels):
        db.add(m.PagePanel(project_id=project_id, page_id=page.id, position=i, data=panel.model_dump()))
    invalidate(db, project, ["generate_page_art", "compose_pages", "quality_assurance", "export_pdf"])
    db.commit()
    return serialize(page)


@app.post("/projects/{project_id}/pages/{page_id}/generate")
def generate_page(project_id: str, page_id: str, db: Session = Depends(get_db), user=Depends(current_user)):
    project = owned(db, project_id, user.id)
    page = item(db, m.Page, page_id, project_id)
    return start_job(db, project, "page_art", page.id)


@app.post("/projects/{project_id}/pages/{page_id}/upload")
def upload_page_art(
    project_id: str,
    page_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user=Depends(current_user),
):
    project = owned(db, project_id, user.id)
    idle(db, project_id)
    page = item(db, m.Page, page_id, project_id)
    script = db.scalar(select(m.PageScript).where(m.PageScript.page_id == page.id))
    key = Storage().put(project_id, image_payload(file), "png", "image/png")
    version = (
        max([a.version for a in records(db, m.PageArtwork, project_id) if a.page_id == page.id], default=0)
        + 1
    )
    artwork = m.PageArtwork(
        project_id=project_id,
        page_id=page.id,
        version=version,
        storage_key=key,
        metadata_json={
            "source": "manual upload",
            "offline": False,
            "script_version": script.version,
            "source_passages": script.data["source_passages"],
            "reference_ids": [],
        },
    )
    db.add(artwork)
    db.flush()
    page.current_artwork_id = artwork.id
    page.approved = False
    invalidate(db, project, ["quality_assurance", "export_pdf"])
    db.commit()
    return serialize(artwork)


@app.post("/projects/{project_id}/pages/{page_id}/qa")
def check_page_art(project_id: str, page_id: str, db: Session = Depends(get_db), user=Depends(current_user)):
    project = owned(db, project_id, user.id)
    page = item(db, m.Page, page_id, project_id)
    if not page.current_artwork_id:
        raise HTTPException(400, "Generate or upload art first")
    return start_job(db, project, "page_qa", page.id)


@app.get("/font")
def book_font():
    from pathlib import Path

    from reportlab.pdfbase import pdfmetrics

    from .exporter import FONT, register_font

    register_font()
    return Response(Path(pdfmetrics.getFont(FONT).face.filename).read_bytes(), media_type="font/ttf")


class NewPage(BaseModel):
    chapter_id: str


@app.post("/projects/{project_id}/pages")
def insert_page(project_id: str, body: NewPage, db: Session = Depends(get_db), user=Depends(current_user)):
    project = owned(db, project_id, user.id)
    idle(db, project_id)
    chapter = item(db, m.Chapter, body.chapter_id, project_id)
    position = max([p.position for p in records(db, m.Page, project_id)], default=-1) + 1
    page = m.Page(
        project_id=project_id,
        chapter_id=chapter.id,
        position=position,
        layout="panels" if project.config["book_type"] == "graphic" else "illustrated",
    )
    db.add(page)
    db.flush()
    script = Script(
        narration="",
        scene="New scene",
        characters=[],
        location="",
        time_of_day="",
        emotional_tone="",
        continuity=[],
        image_prompt="",
        source_passages=[{"start": chapter.start_offset, "end": chapter.end_offset}],
        covered_event_ids=[],
    )
    db.add(m.PageScript(project_id=project_id, page_id=page.id, data=script.model_dump()))
    invalidate(db, project, ["generate_page_art", "compose_pages", "quality_assurance", "export_pdf"])
    db.commit()
    return serialize(page)


@app.delete("/projects/{project_id}/pages/{page_id}")
def delete_page(project_id: str, page_id: str, db: Session = Depends(get_db), user=Depends(current_user)):
    project = owned(db, project_id, user.id)
    idle(db, project_id)
    page = item(db, m.Page, page_id, project_id)
    # Keep an audit snapshot even when the user explicitly removes a page.
    script = db.scalar(select(m.PageScript).where(m.PageScript.page_id == page.id))
    db.add(
        m.GenerationArtifact(
            project_id=project_id,
            stage="deleted_page",
            artifact_key=page.id,
            data={"page": serialize(page), "script": serialize(script)},
        )
    )
    remaining = sorted(
        (p for p in records(db, m.Page, project_id) if p.id != page.id), key=lambda p: p.position
    )
    for position, retained in enumerate(remaining):
        retained.position = position
    db.delete(page)
    invalidate(db, project, ["quality_assurance", "export_pdf"])
    db.commit()
    return {"ok": True}


class PageOrder(BaseModel):
    ids: list[str] = Field(max_length=5000)


@app.put("/projects/{project_id}/page-order")
def reorder(project_id: str, body: PageOrder, db: Session = Depends(get_db), user=Depends(current_user)):
    project = owned(db, project_id, user.id)
    idle(db, project_id)
    pages = records(db, m.Page, project_id)
    if len(body.ids) != len(pages) or set(body.ids) != {p.id for p in pages}:
        raise HTTPException(400, "Order must contain every page exactly once")
    for page in pages:
        page.position = body.ids.index(page.id)
    invalidate(db, project, ["quality_assurance", "export_pdf"])
    db.commit()
    return {"ok": True}


class CoverInput(BaseModel):
    title: str = Field(max_length=240)
    subtitle: str = Field(default="", max_length=240)
    author: str = Field(max_length=240)
    adaptation_credit: str = Field(default="", max_length=240)
    series: str = Field(default="", max_length=240)
    volume: str = Field(default="", max_length=40)
    publisher: str = Field(default="", max_length=240)
    back_text: str = Field(default="", max_length=4000)
    artwork_approved: bool = False


@app.put("/projects/{project_id}/cover")
def edit_cover(project_id: str, body: CoverInput, db: Session = Depends(get_db), user=Depends(current_user)):
    project = owned(db, project_id, user.id)
    idle(db, project_id)
    project.cover = {**project.cover, **body.model_dump()}
    invalidate(db, project, ["export_pdf"])
    db.commit()
    return project.cover


@app.post("/projects/{project_id}/cover/generate")
def generate_cover(project_id: str, db: Session = Depends(get_db), user=Depends(current_user)):
    return start_job(db, owned(db, project_id, user.id), "cover")


@app.post("/projects/{project_id}/cover/upload")
def upload_cover(
    project_id: str, file: UploadFile = File(...), db: Session = Depends(get_db), user=Depends(current_user)
):
    project = owned(db, project_id, user.id)
    idle(db, project_id)
    key = Storage().put(project_id, image_payload(file), "png", "image/png")
    project.cover = {
        **project.cover,
        "artwork_key": key,
        "artwork_approved": False,
        "metadata": {"source": "manual", "offline": False},
    }
    invalidate(db, project, ["export_pdf"])
    db.commit()
    return project.cover


@app.post("/projects/{project_id}/style/references")
def upload_style_reference(
    project_id: str, file: UploadFile = File(...), db: Session = Depends(get_db), user=Depends(current_user)
):
    project = owned(db, project_id, user.id)
    idle(db, project_id)
    references = project.config.get("style_reference_keys", [])
    if len(references) >= 3:
        raise HTTPException(400, "At most three global style reference images are supported")
    key = Storage().put(project_id, image_payload(file), "png", "image/png")
    project.config = {**project.config, "style_reference_keys": list(dict.fromkeys([*references, key]))}
    for page in records(db, m.Page, project_id):
        page.approved = False
    project.cover = {**project.cover, "artwork_approved": False}
    invalidate(db, project, ["generate_page_art", "quality_assurance", "export_pdf"])
    db.commit()
    return {"keys": project.config["style_reference_keys"]}


@app.put("/projects/{project_id}/print")
def edit_print(
    project_id: str, body: PrintSettings, db: Session = Depends(get_db), user=Depends(current_user)
):
    project = owned(db, project_id, user.id)
    idle(db, project_id)
    project.config = {**project.config, "print": body.model_dump()}
    invalidate(db, project, ["export_pdf"])
    db.commit()
    return body


@app.post("/projects/{project_id}/exports")
def make_export(project_id: str, db: Session = Depends(get_db), user=Depends(current_user)):
    project = owned(db, project_id, user.id)
    idle(db, project_id)
    exported = export_book(db, project)
    project.status = "completed" if exported.manifest["qa"]["publication_ready"] else "proof_exported"
    db.commit()
    return serialize(exported)


class JobControl(BaseModel):
    action: str = Field(pattern="^(pause|resume|retry|cancel)$")
    approve_batch: bool = False


@app.post("/projects/{project_id}/jobs/{job_id}/control")
def job_control(
    project_id: str, job_id: str, body: JobControl, db: Session = Depends(get_db), user=Depends(current_user)
):
    project = owned(db, project_id, user.id)
    job = item(db, m.GenerationJob, job_id, project_id)
    if body.action in ("pause", "cancel"):
        job.control = body.action
        if job.status != "running":
            job.status = "cancelled" if body.action == "cancel" else "paused"
    else:
        if job.status not in ("paused", "review", "failed"):
            raise HTTPException(409, "Only paused, review or failed jobs can resume")
        idle(db, project_id)
        if body.approve_batch:
            if job.stage not in ("generate_character_references", "generate_page_art"):
                raise HTTPException(400, "No spending batch is awaiting authorization at this stage")
            project.config = {
                **project.config,
                "batch_approvals": {**project.config.get("batch_approvals", {}), job.stage: True},
            }
        job.control = "run"
        job.status = "queued"
        job.error = None
    db.commit()
    if job.status == "queued":
        try:
            enqueue(job.id)
        except Exception:
            logger.warning("queue_dispatch_deferred", extra={"job_id": job.id})
    return serialize(job)


class UsageResolution(BaseModel):
    charged: bool
    confirm_retry_may_charge_again: bool


@app.post("/projects/{project_id}/usage/{usage_id}/resolve")
def resolve_usage(
    project_id: str,
    usage_id: str,
    body: UsageResolution,
    db: Session = Depends(get_db),
    user=Depends(current_user),
):
    owned(db, project_id, user.id)
    idle(db, project_id)
    usage = item(db, m.UsageRecord, usage_id, project_id)
    if usage.status != "reserved" or not body.confirm_retry_may_charge_again:
        raise HTTPException(400, "Confirm the provider outcome and that a retry can incur another charge")
    usage.status = "reconciled_charged" if body.charged else "reconciled_free"
    if not body.charged:
        usage.cost_usd = 0
    usage.operation_key = f"reconciled:{usage.id}"
    db.commit()
    return serialize(usage)


@app.get("/projects/{project_id}/assets/{key:path}")
def asset(project_id: str, key: str, db: Session = Depends(get_db), user=Depends(current_user)):
    owned(db, project_id, user.id)
    if not key.startswith(project_id + "/"):
        raise HTTPException(404, "Asset not found")
    try:
        payload = Storage().get(key)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, "Asset not found")
    content_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
    return Response(
        payload,
        media_type=content_type,
        headers={"Content-Disposition": f'inline; filename="{key.rsplit("/", 1)[-1]}"'},
    )


@app.get("/projects/{project_id}/events")
async def events(
    project_id: str, request: Request, db: Session = Depends(get_db), user=Depends(current_user)
):
    owned(db, project_id, user.id)
    # Dependency cleanup waits for SSE to finish; release its auth read snapshot before streaming.
    # Otherwise initial PostgreSQL checkpoint indexes can wait indefinitely on this transaction.
    db.commit()

    async def stream():
        last = ""
        while not await request.is_disconnected():
            with SessionLocal() as session:
                jobs = [serialize(j) for j in records(session, m.GenerationJob, project_id)]
                payload = json.dumps({"jobs": jobs})
            if payload != last:
                yield f"event: progress\ndata: {payload}\n\n"
                last = payload
            else:
                yield ": heartbeat\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})
