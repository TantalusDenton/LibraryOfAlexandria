import json
from contextlib import contextmanager
from typing import TypedDict

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from sqlalchemy import select

from .ai import AI
from .config import settings
from .db import now
from .ingestion import chunks, detect_chapters
from .models import (
    BookProject,
    Chapter,
    ChapterSummary,
    Character,
    CharacterReference,
    GenerationArtifact,
    Location,
    Page,
    PageArtwork,
    PageLayoutElement,
    PagePanel,
    PageScript,
    SourceDocument,
    WorkflowCheckpoint,
)
from .schemas import CharacterDesign, CharacterList, Plan, Script, StoryAnalysis, Summary
from .storage import Storage
from .styles import style_prompt

STAGES = [
    "ingest_source",
    "detect_chapters",
    "summarize_chapters",
    "analyze_full_story",
    "extract_characters",
    "generate_character_bible",
    "generate_character_references",
    "plan_pages",
    "generate_page_scripts",
    "generate_page_art",
    "compose_pages",
    "quality_assurance",
    "export_pdf",
]


class ReviewRequired(Exception):
    pass


class JobStopped(Exception):
    pass


class State(TypedDict):
    project_id: str
    job_id: str
    last_stage: str


class Workflow:
    def __init__(self, db, job):
        self.db, self.job = db, job
        self.project = db.get(BookProject, job.project_id)
        self.storage = Storage()
        self.ai = AI(db, self.project)

    def rows(self, cls, **filters):
        return list(
            self.db.scalars(
                select(cls).filter_by(project_id=self.project.id, **filters).order_by(cls.created_at)
            )
        )

    def artifact(self, stage, key):
        return self.db.scalar(
            select(GenerationArtifact).where(
                GenerationArtifact.project_id == self.project.id,
                GenerationArtifact.stage == stage,
                GenerationArtifact.artifact_key == key,
            )
        )

    def record(self, stage, key, data):
        if existing := self.artifact(stage, key):
            return existing
        value = GenerationArtifact(project_id=self.project.id, stage=stage, artifact_key=key, data=data)
        self.db.add(value)
        self.db.commit()
        return value

    def guard(self):
        self.db.refresh(self.job)
        if self.job.control != "run":
            raise JobStopped(self.job.control)
        self.job.heartbeat = now()
        self.db.commit()

    def run_stage(self, stage, state):
        self.guard()
        self.job.stage = stage
        self.job.progress = int(100 * STAGES.index(stage) / len(STAGES))
        self.project.status = stage
        self.db.commit()
        checkpoint = self.db.scalar(
            select(WorkflowCheckpoint).filter_by(project_id=self.project.id, stage=stage)
        )
        if not checkpoint:
            getattr(self, stage)()
            self.db.add(
                WorkflowCheckpoint(project_id=self.project.id, stage=stage, data={"job_id": self.job.id})
            )
            self.db.commit()
        return {**state, "last_stage": stage}

    def ingest_source(self):
        if not self.rows(SourceDocument):
            raise ValueError("Upload or import a manuscript first")

    def detect_chapters(self):
        if self.rows(Chapter):
            return
        source = self.rows(SourceDocument)[0]
        text = self.storage.get(source.storage_key).decode()
        for data in detect_chapters(text):
            self.db.add(Chapter(project_id=self.project.id, source_id=source.id, **data))
        self.db.commit()

    def summarize_chapters(self):
        source = self.rows(SourceDocument)[0]
        manuscript = self.storage.get(source.storage_key).decode()
        for chapter in sorted(self.rows(Chapter), key=lambda x: x.position):
            self.guard()
            if self.rows(ChapterSummary, chapter_id=chapter.id):
                continue
            summaries, source_events, source_names = [], [], []
            text = manuscript[chapter.start_offset : chapter.end_offset]
            for offset, part in chunks(text):
                self.guard()
                result = self.ai.structured(
                    Summary,
                    "Summarize this source passage in detail. Include all essential events, names, locations, dialogue and developments.",
                    {
                        "text": part,
                        "source_start": chapter.start_offset + offset,
                        "language": self.project.config["output_language"],
                    },
                    f"chunk:{chapter.id}:{offset}",
                )
                summaries.append(result.model_dump())
                source_events.extend(e.model_dump() for e in result.events)
                source_names.extend(result.characters)
            # Persist every level via the AI cache; no entire novel goes into a single context window.
            level = 0
            while len(summaries) > 1:
                next_level = []
                for i in range(0, len(summaries), 4):
                    self.guard()
                    merged = self.ai.structured(
                        Summary,
                        "Merge these ordered partial summaries. Preserve every essential plot event and all characters. Assign unique event IDs.",
                        {"summaries": summaries[i : i + 4]},
                        f"merge:{chapter.id}:{level}:{i}",
                    )
                    next_level.append(merged.model_dump())
                summaries = next_level
                level += 1
            data = summaries[0]
            # Hierarchical prose compression must never erase the original chunk event ledger or cast.
            data["events"] = source_events
            data["characters"] = list(dict.fromkeys(source_names))
            # IDs are chapter-local, stable and unique even if an LLM repeats labels.
            for i, event in enumerate(data["events"]):
                event["id"] = f"{chapter.id}:e{i + 1}"
            self.db.add(ChapterSummary(project_id=self.project.id, chapter_id=chapter.id, data=data))
            self.db.commit()

    def analyze_full_story(self):
        if self.artifact("story", "analysis"):
            return
        ordered = sorted(self.rows(Chapter), key=lambda c: c.position)
        summaries = [self.rows(ChapterSummary, chapter_id=c.id)[0].data for c in ordered]
        level = 0
        while len(json.dumps(summaries)) > 40000 or len(summaries) > 8:
            merged = []
            for i in range(0, len(summaries), 4):
                self.guard()
                merged.append(
                    self.ai.structured(
                        Summary,
                        "Merge sequential chapter summaries, retaining major causes, consequences, identities and ending.",
                        {"summaries": summaries[i : i + 4]},
                        f"story-tree:{level}:{i}",
                    ).model_dump()
                )
            summaries = merged
            level += 1
        analysis = self.ai.structured(
            StoryAnalysis,
            "Analyze the complete story and ending. Define an explicit condensation strategy; essential chapter events must be assigned to pages, never silently discarded.",
            {
                "summaries": summaries,
                "pages_per_chapter": self.project.config["pages_per_chapter"],
                "output_language": self.project.config["output_language"],
                "audience": self.project.config["audience"],
                "tone": self.project.config["tone"],
            },
            "full-story",
        )
        self.record("story", "analysis", analysis.model_dump())

    def extract_characters(self):
        existing = {c.name.casefold(): c for c in self.rows(Character)}
        # Process every chapter, even characters omitted by upper-level story compression.
        for summary in self.rows(ChapterSummary):
            self.guard()
            result = self.ai.structured(
                CharacterList,
                "Extract all principal and supporting characters. Include aliases, relationships, timelines and canonical visual details. Mark unspecified facts explicitly.",
                {
                    "names": summary.data["characters"],
                    "summary": summary.data,
                    "style": style_prompt(self.project),
                },
                f"characters:{summary.chapter_id}",
            )
            for design in result.characters:
                folded = design.name.casefold()
                identities = {folded, *(alias.casefold() for alias in design.aliases)}
                char = next(
                    (
                        c
                        for c in existing.values()
                        if identities
                        & {c.name.casefold(), *(a.casefold() for a in c.data.get("aliases", []))}
                    ),
                    None,
                )
                if char and not char.locked:
                    merged = self.ai.structured(
                        CharacterDesign,
                        "Merge chapter evidence into this existing character bible. Retain the canonical name and prior facts; accumulate relationships and timeline. Do not invent unspecified physical traits.",
                        {"existing": char.data, "discovered": design.model_dump()},
                        f"character-merge:{char.id}:{summary.chapter_id}",
                    )
                    char.data = merged.model_dump()
                elif not char:
                    char = Character(project_id=self.project.id, name=design.name, data=design.model_dump())
                    self.db.add(char)
                    existing[folded] = char
            self.db.commit()
            for name in summary.data["locations"]:
                if not self.rows(Location, name=name):
                    self.db.add(Location(project_id=self.project.id, name=name, data={"description": name}))
            self.db.commit()

    def generate_character_bible(self):
        self.record("characters", "bible", {"characters": [c.data for c in self.rows(Character)]})

    def require_batch(self, stage):
        self.db.refresh(self.project)
        if not self.project.config.get("batch_approvals", {}).get(stage):
            raise ReviewRequired(f"Review and explicitly authorize the {stage} batch before spending")

    def generate_character_references(self):
        if any(not s.approved for s in self.rows(ChapterSummary)):
            raise ReviewRequired("Review and approve every chapter summary before illustration")
        missing = [c for c in self.rows(Character) if not self.rows(CharacterReference, character_id=c.id)]
        if missing:
            self.require_batch("generate_character_references")
        for character in missing:
            self.guard()
            self.portrait(character)

    def portrait(self, character, force=False):
        completed = next(
            (
                r
                for r in self.rows(CharacterReference, character_id=character.id)
                if r.metadata_json.get("job_id") == self.job.id
            ),
            None,
        )
        if completed and not force:
            return completed
        if character.locked:
            raise ReviewRequired("Unlock the character explicitly before making a new portrait")
        version = (
            max([r.version for r in self.rows(CharacterReference, character_id=character.id)], default=0) + 1
        )
        prompt = f"Canonical character reference portrait, full costume, neutral background. {style_prompt(self.project)}\n{json.dumps(character.data)}"
        payload, metadata = self.ai.image(
            prompt, self.style_references(), f"portrait:{character.id}:{version}"
        )
        if payload:
            key = self.storage.put(self.project.id, payload, "png", "image/png")
            metadata["storage_key"] = key
            self.ai.save(metadata["cache_key"], metadata["prompt"], metadata)
        else:
            key = metadata["storage_key"]
        metadata = {**metadata, "job_id": self.job.id}
        ref = CharacterReference(
            project_id=self.project.id,
            character_id=character.id,
            storage_key=key,
            version=version,
            metadata_json=metadata,
        )
        self.db.add(ref)
        self.db.commit()
        return ref

    def plan_pages(self):
        if any(not c.locked or not c.approved_reference_id for c in self.rows(Character)):
            raise ReviewRequired("Approve and lock all canonical character references before planning pages")
        for chapter in sorted(self.rows(Chapter), key=lambda c: c.position):
            self.guard()
            if self.artifact("plan", chapter.id):
                continue
            summary = self.rows(ChapterSummary, chapter_id=chapter.id)[0]
            count = self.project.config["pages_per_chapter"]
            plan = self.ai.structured(
                Plan,
                "Create exactly count page briefs, assigning every essential event ID to a zero-based page index. Explain condensation and preserve causal continuity.",
                {"count": count, "summary": summary.data},
                f"plan:{chapter.id}",
            )
            essential = {e["id"] for e in summary.data["events"] if e["essential"]}
            if (
                len(plan.page_briefs) != count
                or not essential.issubset(plan.event_to_page)
                or any(i < 0 or i >= count for i in plan.event_to_page.values())
            ):
                raise ValueError(
                    "Page plan omitted essential events or returned an invalid page count; review summary and retry"
                )
            self.record("plan", chapter.id, {**plan.model_dump(), "event_to_page": plan.event_to_page})
            for i in range(count):
                self.db.add(
                    Page(
                        project_id=self.project.id,
                        chapter_id=chapter.id,
                        position=chapter.position * count + i,
                        layout="panels" if self.project.config["book_type"] == "graphic" else "illustrated",
                    )
                )
            self.db.commit()

    def generate_page_scripts(self):
        for page in sorted(self.rows(Page), key=lambda p: p.position):
            self.guard()
            if self.rows(PageScript, page_id=page.id):
                continue
            chapter = self.db.get(Chapter, page.chapter_id)
            summary = self.rows(ChapterSummary, chapter_id=chapter.id)[0]
            plan = self.artifact("plan", chapter.id).data
            chapter_pages = sorted(self.rows(Page, chapter_id=chapter.id), key=lambda p: p.position)
            index = chapter_pages.index(page)
            events = [e for e in summary.data["events"] if plan["event_to_page"].get(e["id"]) == index]
            script = self.ai.structured(
                Script,
                "Write one page adaptation in the output language. Cover all assigned events, keep source passage offsets inside the provided chapter range. Use only canonical character names. For graphic mode use 2-6 panels; no text baked into art.",
                {
                    "summary": summary.data,
                    "events": events,
                    "brief": plan["page_briefs"][index],
                    "passage": {"start": chapter.start_offset, "end": chapter.end_offset},
                    "book_type": self.project.config["book_type"],
                    "output_language": self.project.config["output_language"],
                    "characters": [
                        c.data
                        for c in self.rows(Character)
                        if c.name in summary.data["characters"]
                        or set(c.data.get("aliases", [])) & set(summary.data["characters"])
                    ],
                },
                f"script:{page.id}",
            )
            if not {e["id"] for e in events}.issubset(script.covered_event_ids):
                raise ValueError("Page script omitted assigned essential events")
            if any(
                p.start < chapter.start_offset or p.end > chapter.end_offset or p.end <= p.start
                for p in script.source_passages
            ):
                raise ValueError("Page script returned invalid source passage offsets")
            self.db.add(PageScript(project_id=self.project.id, page_id=page.id, data=script.model_dump()))
            for i, panel in enumerate(script.panels):
                self.db.add(
                    PagePanel(
                        project_id=self.project.id, page_id=page.id, position=i, data=panel.model_dump()
                    )
                )
            self.db.commit()

    def references(self, script):
        references, descriptions = [], []
        characters = self.rows(Character)
        for name in script["characters"]:
            c = next(
                (
                    c
                    for c in characters
                    if c.name.casefold() == name.casefold()
                    or name.casefold() in [a.casefold() for a in c.data.get("aliases", [])]
                ),
                None,
            )
            if not c or not c.locked or not c.approved_reference_id:
                raise ReviewRequired(f"Approve a canonical reference for {name}")
            ref = self.db.get(CharacterReference, c.approved_reference_id)
            if not ref or ref.character_id != c.id:
                raise ValueError("Invalid canonical reference")
            references.append((f"{c.id}@{ref.version}", self.storage.get(ref.storage_key)))
            descriptions.append(c.data)
        return references, descriptions

    def style_references(self):
        return [
            (f"style:{key.rsplit('/', 1)[-1]}", self.storage.get(key))
            for key in self.project.config.get("style_reference_keys", [])
        ]

    def page_art(self, page):
        script = self.rows(PageScript, page_id=page.id)[0]
        if not script.approved:
            raise ReviewRequired("Approve this page script before generating art")
        references, descriptions = self.references(script.data)
        completed = next(
            (
                a
                for a in self.rows(PageArtwork, page_id=page.id)
                if a.metadata_json.get("job_id") == self.job.id
            ),
            None,
        )
        if completed:
            if (
                completed.id != page.current_artwork_id
                or completed.metadata_json.get("script_version") != script.version
            ):
                raise ReviewRequired(
                    "This job's artwork was superseded or its script changed. Start a new page generation explicitly."
                )
            qa = self.ai.visual_qa(self.storage.get(completed.storage_key), references, script.data)
            self.record("visual_qa", completed.id, qa.model_dump())
            return completed
        version = max([a.version for a in self.rows(PageArtwork, page_id=page.id)], default=0) + 1
        prompt = (
            f"{style_prompt(self.project)}\nCanonical characters: {json.dumps(descriptions)}\n"
            f"Page script: {json.dumps(script.data)}\nLayout: {page.layout}. "
            "For panels compose separate clear panel regions; leave room for deterministic text overlays."
        )
        payload, metadata = self.ai.image(
            prompt, references + self.style_references(), f"art:{page.id}:{version}"
        )
        if payload:
            key = self.storage.put(self.project.id, payload, "png", "image/png")
            metadata.update(
                storage_key=key, source_passages=script.data["source_passages"], script_version=script.version
            )
            self.ai.save(metadata["cache_key"], prompt, metadata)
        else:
            key = metadata["storage_key"]
        metadata = {**metadata, "job_id": self.job.id}
        art = PageArtwork(
            project_id=self.project.id,
            page_id=page.id,
            version=version,
            storage_key=key,
            metadata_json=metadata,
        )
        self.db.add(art)
        self.db.flush()
        page.current_artwork_id = art.id
        page.approved = False
        self.db.commit()
        qa = self.ai.visual_qa(self.storage.get(key), references, script.data)
        self.record("visual_qa", art.id, qa.model_dump())
        return art

    def generate_page_art(self):
        if any(not s.approved for s in self.rows(PageScript)):
            raise ReviewRequired("Review and approve every page script before generating illustrations")
        missing = [p for p in self.rows(Page) if not p.current_artwork_id]
        if missing:
            self.require_batch("generate_page_art")
        for page in missing:
            self.guard()
            self.page_art(page)

    def compose_page(self, page):
        if self.rows(PageLayoutElement, page_id=page.id):
            return
        script = self.rows(PageScript, page_id=page.id)[0]
        if page.layout == "panels" and script.data["panels"]:
            n = len(script.data["panels"])
            for i, panel in enumerate(script.data["panels"]):
                for j, text in enumerate(
                    ([panel["narration"]] if panel["narration"] else []) + panel["dialogue"]
                ):
                    self.db.add(
                        PageLayoutElement(
                            project_id=self.project.id,
                            page_id=page.id,
                            kind="caption" if j == 0 else "speech",
                            data=dict(
                                text=text,
                                x=0.06,
                                y=min(0.9, i / n + 0.04 + j * 0.07),
                                width=0.86,
                                height=min(0.15, 0.85 / n),
                                font_size=11,
                            ),
                        )
                    )
        else:
            self.db.add(
                PageLayoutElement(
                    project_id=self.project.id,
                    page_id=page.id,
                    kind="narration",
                    data=dict(
                        text=script.data["narration"], x=0.08, y=0.72, width=0.84, height=0.20, font_size=12
                    ),
                )
            )
        self.db.commit()

    def compose_pages(self):
        for page in self.rows(Page):
            self.compose_page(page)

    def quality_assurance(self):
        issues = []
        for page in self.rows(Page):
            if not page.approved:
                issues.append(f"Page {page.position + 1} awaits approval")
            script = self.rows(PageScript, page_id=page.id)[0]
            if not script.data.get("source_passages"):
                issues.append(f"Page {page.position + 1} has no source references")
        self.record("qa", "narrative", {"issues": issues, "offline": not self.ai.live})

    def export_pdf(self):
        if any(not p.approved for p in self.rows(Page)):
            raise ReviewRequired("Review and approve all pages before the final export stage")
        if not self.project.cover.get("artwork_key"):
            raise ReviewRequired("Generate or upload cover artwork before export")
        from .exporter import export_book

        export_book(self.db, self.project)

    def cover_art(self):
        if self.project.cover.get("metadata", {}).get("job_id") == self.job.id:
            return
        if any(
            a.data.get("job_id") == self.job.id for a in self.rows(GenerationArtifact) if a.stage == "cover"
        ):
            raise ReviewRequired(
                "A newer cover superseded this job's result. Start a new cover job explicitly."
            )
        version = len([a for a in self.rows(GenerationArtifact) if a.stage == "cover"]) + 1
        analysis = self.artifact("story", "analysis")
        prompt = (
            f"Front cover artwork, no typography. {style_prompt(self.project)}. "
            f"{analysis.data['synopsis'] if analysis else self.project.title}"
        )
        references = []
        for c in self.rows(Character):
            if c.locked and c.approved_reference_id:
                ref = self.db.get(CharacterReference, c.approved_reference_id)
                references.append((f"{c.id}@{ref.version}", self.storage.get(ref.storage_key)))
        payload, metadata = self.ai.image(prompt, references + self.style_references(), f"cover:{version}")
        if payload:
            key = self.storage.put(self.project.id, payload, "png", "image/png")
            metadata["storage_key"] = key
            self.ai.save(metadata["cache_key"], prompt, metadata)
        else:
            key = metadata["storage_key"]
        metadata = {**metadata, "job_id": self.job.id}
        self.project.cover = {
            **self.project.cover,
            "artwork_key": key,
            "artwork_approved": False,
            "metadata": metadata,
        }
        self.record("cover", f"v{version}", metadata)
        self.db.commit()


@contextmanager
def checkpointer():
    url = settings().checkpoint_url
    if url.startswith("sqlite:///"):
        with SqliteSaver.from_conn_string(url.removeprefix("sqlite:///")) as saver:
            yield saver
    else:
        with PostgresSaver.from_conn_string(url) as saver:
            saver.setup()
            yield saver


def run_graph(db, job):
    workflow = Workflow(db, job)
    # Postgres checkpoint schema setup uses concurrent index creation; do not hold an old read snapshot.
    db.commit()
    graph = StateGraph(State)
    for stage in STAGES:
        graph.add_node(stage, lambda state, name=stage: workflow.run_stage(name, state))
    graph.add_edge(START, STAGES[0])
    for left, right in zip(STAGES, STAGES[1:]):
        graph.add_edge(left, right)
    graph.add_edge(STAGES[-1], END)
    with checkpointer() as saver:
        compiled = graph.compile(checkpointer=saver)
        # Each job has a graph thread. DB stage/artifact checkpoints span retries and new jobs as well.
        compiled.invoke(
            {"project_id": job.project_id, "job_id": job.id, "last_stage": ""},
            {"configurable": {"thread_id": job.id}, "recursion_limit": 50},
        )
