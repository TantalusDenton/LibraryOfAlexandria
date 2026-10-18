from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, now, uid


class Record:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class User(Record, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)


class BookProject(Record, Base):
    __tablename__ = "book_projects"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(240))
    author: Mapped[str] = mapped_column(String(240))
    rights_confirmed: Mapped[bool] = mapped_column(Boolean)
    rights_declaration: Mapped[str] = mapped_column(Text)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(40), default="draft")
    budget_usd: Mapped[float] = mapped_column(Float, default=25)
    cover: Mapped[dict] = mapped_column(JSON, default=dict)


class ProjectRecord(Record):
    project_id: Mapped[str] = mapped_column(ForeignKey("book_projects.id", ondelete="CASCADE"), index=True)


class SourceDocument(ProjectRecord, Base):
    __tablename__ = "source_documents"
    source_url: Mapped[str | None] = mapped_column(Text)
    original_author: Mapped[str] = mapped_column(Text)
    edition: Mapped[str] = mapped_column(Text, default="Unspecified")
    rights: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    char_count: Mapped[int] = mapped_column(Integer)


class Chapter(ProjectRecord, Base):
    __tablename__ = "chapters"
    __table_args__ = (UniqueConstraint("project_id", "position"),)
    source_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"))
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    start_offset: Mapped[int] = mapped_column(Integer)
    end_offset: Mapped[int] = mapped_column(Integer)


class ChapterSummary(ProjectRecord, Base):
    __tablename__ = "chapter_summaries"
    chapter_id: Mapped[str] = mapped_column(ForeignKey("chapters.id"), unique=True)
    data: Mapped[dict] = mapped_column(JSON)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)


class Character(ProjectRecord, Base):
    __tablename__ = "characters"
    name: Mapped[str] = mapped_column(String(240))
    data: Mapped[dict] = mapped_column(JSON)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_reference_id: Mapped[str | None] = mapped_column(String(36))


class CharacterReference(ProjectRecord, Base):
    __tablename__ = "character_references"
    __table_args__ = (UniqueConstraint("character_id", "version"),)
    character_id: Mapped[str] = mapped_column(ForeignKey("characters.id"), index=True)
    storage_key: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class Location(ProjectRecord, Base):
    __tablename__ = "locations"
    name: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON)


class StylePreset(Record, Base):
    __tablename__ = "style_presets"
    name: Mapped[str] = mapped_column(String(240), unique=True)
    data: Mapped[dict] = mapped_column(JSON)


class Page(ProjectRecord, Base):
    __tablename__ = "pages"
    chapter_id: Mapped[str] = mapped_column(ForeignKey("chapters.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    layout: Mapped[str] = mapped_column(String(40), default="illustrated")
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    current_artwork_id: Mapped[str | None] = mapped_column(String(36))


class PagePanel(ProjectRecord, Base):
    __tablename__ = "page_panels"
    page_id: Mapped[str] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSON)


class PageScript(ProjectRecord, Base):
    __tablename__ = "page_scripts"
    page_id: Mapped[str] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), unique=True)
    data: Mapped[dict] = mapped_column(JSON)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)


class PageArtwork(ProjectRecord, Base):
    __tablename__ = "page_artworks"
    page_id: Mapped[str] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), index=True)
    storage_key: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    metadata_json: Mapped[dict] = mapped_column(JSON)


class PageLayoutElement(ProjectRecord, Base):
    __tablename__ = "page_layout_elements"
    page_id: Mapped[str] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    data: Mapped[dict] = mapped_column(JSON)


class GenerationJob(ProjectRecord, Base):
    __tablename__ = "generation_jobs"
    __table_args__ = (Index("jobs_status_created", "status", "created_at"),)
    kind: Mapped[str] = mapped_column(String(40), default="workflow")
    target_id: Mapped[str | None] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(40), default="queued")
    stage: Mapped[str] = mapped_column(String(80), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    control: Mapped[str] = mapped_column(String(40), default="run")
    heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GenerationArtifact(ProjectRecord, Base):
    __tablename__ = "generation_artifacts"
    __table_args__ = (UniqueConstraint("project_id", "stage", "artifact_key", "version"),)
    stage: Mapped[str] = mapped_column(String(80))
    artifact_key: Mapped[str] = mapped_column(String(120))
    version: Mapped[int] = mapped_column(Integer, default=1)
    prompt_version: Mapped[str] = mapped_column(String(40), default="2026-10-v1")
    prompt: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict] = mapped_column(JSON)


class WorkflowCheckpoint(ProjectRecord, Base):
    __tablename__ = "workflow_checkpoints"
    __table_args__ = (UniqueConstraint("project_id", "stage"),)
    stage: Mapped[str] = mapped_column(String(80))
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class UsageRecord(ProjectRecord, Base):
    __tablename__ = "usage_records"
    operation_key: Mapped[str] = mapped_column(String(240), unique=True)
    model: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), default="reserved")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    image_calls: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float)
    pricing_basis: Mapped[str] = mapped_column(Text)


class Export(ProjectRecord, Base):
    __tablename__ = "exports"
    interior_key: Mapped[str] = mapped_column(Text)
    cover_key: Mapped[str] = mapped_column(Text)
    zip_key: Mapped[str] = mapped_column(Text)
    manifest: Mapped[dict] = mapped_column(JSON)


class QualityReport(ProjectRecord, Base):
    __tablename__ = "quality_reports"
    export_id: Mapped[str | None] = mapped_column(ForeignKey("exports.id"))
    data: Mapped[dict] = mapped_column(JSON)
    passed: Mapped[bool] = mapped_column(Boolean)
