# Library of Alexandria

**Turn stories into worlds.**

A working publishing-studio MVP for adapting manuscripts into illustrated novels and graphic novels. The Next.js studio connects to a FastAPI service, a persisted LangGraph workflow, durable jobs, versioned image artifacts, and a deterministic print-PDF exporter. There is no preloaded fictional bookshelf or simulated progress.

## Run locally

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 22+, and npm. Python and JavaScript dependencies are locked in `backend/uv.lock` and `frontend/package-lock.json`.

```bash
cp .env.example .env
bash scripts/install.sh
bash scripts/dev.sh
```

The studio uses port 3000 and the API uses port 8000. Create an account in the studio. The interactive API reference is at `/docs` on the API service. `GET /health` checks database access. Start all three processes; an API without a worker cannot generate books. No public cloud account is needed for local operation.

The default is **offline testing mode**. It uses deterministic extractive analysis and visibly labeled test illustrations, makes no OpenAI calls, and marks its exports as proofs that must not be published. Offline mode does not pretend to provide translation, creative analysis, or visual-identity verification.

Local state lives in `backend/data/`: SQLite relational data, LangGraph checkpoints, object files, and a private persistent session-signing key. These files and `.env` are ignored by Git. Do not delete them to restart the app. The setup script applies migrations without resetting existing data. Run commands from the documented directories: relative database URLs and `.env` loading depend on them.

For separate terminals:

```bash
cd backend
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
# second terminal, also in backend:
.venv/bin/python -m app.worker
# third terminal:
cd frontend
npm run dev
```

For a production Next.js build, run `npm run build`, then copy `.next/static` into `.next/standalone/.next/static` and `public` into `.next/standalone/public`, and run `node .next/standalone/server.js`. The Dockerfile handles this automatically. `API_URL` is read at runtime by the same-origin API proxy, so the browser never needs the private backend address or API credentials.

## Docker Compose

Copy `.env.example` to `.env`. Set a URL-safe `POSTGRES_PASSWORD` (32 random hexadecimal characters work well) and a random `JWT_SECRET` of at least 32 characters. Never commit either value.

```bash
docker compose up --build
```

Compose runs PostgreSQL 17, Redis 7 with append-only persistence, a one-shot migration service, API, RQ worker supervisor, and Next.js. Only the API and studio are bound to loopback host ports; database and Redis ports stay private. Named volumes retain relational data, Redis jobs, and object storage. The API and worker share the object volume and session configuration. Do not use `docker compose down -v` unless you intend to delete all data.

Build containers need DNS and access to PyPI and npm. If a managed cloud uses an egress proxy, `python scripts/cloud_build.py` builds the Compose images through the existing proxy, forwards its hostname mapping, and supplies its existing trusted CA as an optional BuildKit secret. Then use `docker compose up --no-build`. Both Dockerfiles accept the `build_ca` secret in other deployments too. Package hashes and TLS verification remain enabled. The container network must be able to reach the proxy. Do not solve network failures by disabling TLS.

## Use the studio

For the Azure Consumption deployment with private PostgreSQL, Blob Storage, managed identities, and scale-to-zero container jobs, see [the Azure deployment guide](deploy/azure/README.md). The deployment command keeps AI offline, disables public registration, creates an initial owner account, and configures budget alerts. Azure access and subscription-side validation are required before it can be considered deployed.

1. **Create a book.** Enter the title, original author, source edition, original/output languages, audience, tone, format, 1–5 pages per original chapter, style, trim, paper, quality, models, and budget. Upload TXT or import a public HTTP(S) source. Confirm rights in the intended publishing markets and record the basis. The Ivanhoe preset supplies Scott’s title, a Gutenberg URL, and the requested gothic medieval art direction; it supplies no copyrighted modern illustrations.
2. **Analyze.** Chapters retain character offsets into the complete saved, normalized source document. Unheaded text is divided at paragraphs. Chapter chunks, intermediate hierarchy levels, complete-story analysis, character evidence, and page plans are persisted. The event ledger and cast from source chunks are retained independently of compressed summaries.
3. **Review summaries.** Edit summaries and essential-event flags before approving them. Each page plan must map every essential event to a page. Source passages remain accessible in the editor. Summary revisions after pages are planned require corresponding page-script edits; they do not silently destroy an existing book.
4. **Build the character bible.** Chapter-by-chapter extraction merges names, aliases, relationships, timeline, and visual details across the whole manuscript. Edit descriptions, generate or upload references, select a version, and approve/lock the canonical image. Unlocking is explicit and invalidates page approvals. Portrait and page regeneration never silently replace a locked reference.
5. **Plan and script.** Continue the workflow after character approval. Review each page’s narration, characters, location, time, emotional tone, continuity, scene, image prompt, panels, and source references. Approve scripts before generating artwork. Before large batches the job pauses for explicit authorization. Individual portrait, page, and cover buttons authorize only that operation. You can also upload high-resolution page artwork and explicitly run visual QA against the canonical references.
6. **Edit.** Use the chapter/page tree, reorder controls, insertion/deletion, layout selection, editable narration and dialogue, captions and speech elements, normalized geometry controls, and draggable text boxes. Apply narration changes to layout elements explicitly. Facing-page preview is a reader aid; exports use single pages. Save edits before regenerating art. Deleted scripts and prior edited versions are retained as audit artifacts.
7. **Cover and export.** Edit title, subtitle, original author, adaptation credit, series, volume, imprint, and back text. Generate or upload art, approve it, and select print settings. Optional global style-reference uploads in this screen guide future portraits, pages, and covers; existing canonical images remain intact and page/cover approvals require review again. Export the interior, wraparound cover, or ZIP containing both PDFs, a QA report, and a manifest. Download links enforce project ownership.

The worker pauses at review gates and supports pause, continue, retry, and cancellation. Control changes take effect between calls/items; they cannot undo a provider call already in flight. A worker crash retains stage outputs. After ten minutes without a heartbeat, the supervisor marks an abandoned job failed once it can acquire the project lock. Retry resumes retained outputs and cached operations. Database and graph checkpoints are retained across API/worker restarts.

## Enable real OpenAI generation

Configure **server-side** environment values using `.env` or your deployment’s secret manager:

```dotenv
AI_MODE=live
OPENAI_API_KEY=<supply securely on the server>
PRICING_CONFIRMED=true
```

First confirm the provider’s **current model availability and prices**, and update `TEXT_MODEL`, `IMAGE_MODEL`, `ECONOMY_IMAGE_MODEL`, text-token rates, and conservative preview/final image reservations. The supplied numeric prices are configuration examples, not a quote. Image reservations must cover the complete call, including reference-image input costs. Restart API and worker after changing environment settings. Models and per-project quality are configurable. Never place secrets in `NEXT_PUBLIC_*`, manuscripts, saved prompts, or chat.

Structured calls use the official SDK’s `responses.parse` with Pydantic output schemas. Image calls without references use `images.generate`; page illustrations and covers with references use **`images.edit` with actual multipart image bytes**. References are selected in script order, bounded by `MAX_IMAGE_REFERENCES` and `MAX_REFERENCE_BYTES`; omitted references are recorded and supplemented with canonical descriptions. All image requests exclude lettering. Final typography is rendered separately. Image prompts, model, quality, script/source versions, reference versions, and generated files are retained.

### Budget and usage semantics

Every chargeable operation persists a reservation before the network request. Project locks plus PostgreSQL row locks serialize spending, and a call is refused when its reservation would exceed the project cap. Successful text calls record actual returned token counts using configured rates. Image charges retain conservative configured ceilings because a universal provider invoice total is not returned. The UI labels this **spent and reserved**, not an exact provider bill. Budget accuracy depends on correct conservative pricing; reconcile against provider billing and use provider-level spend controls as well.

Known rejected rate-limited requests retry with exponential jitter, up to three attempts. A timeout, unknown 5xx outcome, or crash without a stored result leaves a reservation. It is never silently refunded or automatically charged a second time. Check the provider result, then reconcile the operation in Exports → Usage before retrying; the UI requires an explicit acknowledgment that another call may charge again. Completed artifacts are content-addressed and cached. A single page can be regenerated without rebuilding the book.

### Paid smoke test (not part of automated tests)

This was **not run during implementation**. It is disabled unless explicitly enabled. Provide a rights-cleared TXT excerpt containing one chapter, at most 5,000 characters, and exactly two named characters. Use a disposable migrated database and current conservative pricing.

```bash
cd backend
PAID_SMOKE_TEST=1 SMOKE_MANUSCRIPT=/absolute/path/to/excerpt.txt \
  SMOKE_BUDGET_USD=5 .venv/bin/python ../scripts/paid_smoke.py
```

This explicitly authorizes test-only automatic approvals. It produces two reference portraits, two reference-based page illustrations, a separate cover illustration, interior PDF, wraparound PDF, QA, and ZIP. That is **five image calls**, plus text and visual-QA calls. It fails before image generation if extraction does not yield exactly two characters. Proofs are retained under the reported project/export IDs. It does not publish anything.

## Print QA and limits

ReportLab embeds a TrueType font and renders narration/dialogue independently from artwork. PyMuPDF verifies every page’s dimensions and page count and inspects font embedding. Export includes title, rights/credits, contents, single interior pages, intentional even-count padding, and a separate back/spine/front cover with a reserved barcode area. Bleed interiors add 0.125 inches on the outside and 0.125 at top/bottom. Cover bleed is 0.125 inches on all outer edges. Gutter grows with actual page count; paper selection affects spine width.

QA flags text clipping, unsupported font glyphs, unsafe text placement, missing event coverage, stale scripts/reference versions, unapproved pages/designs, incomplete visual QA, low effective image DPI, structural PDF problems, short paperback page counts, and offline artwork. Low-resolution assets are **never upscaled or falsely labeled 300 DPI**. Standard generated image sizes will often be insufficient for full-page 6×9-inch printing; use a suitably smaller printed image area or externally produce/quality-check higher-resolution assets. Uploaded page, cover, and reference images are supported. The MVP does not include a learned super-resolution engine. Review the QA report rather than treating every export as print-ready.

The cover uses published paperback spine factors for white, cream, and premium-color paper, suppresses spine lettering below 79 pages, and uses the **actual exported page count**, including front matter and padding. Check the current KDP cover calculator, available trim/paper combinations, color-page-count rules, and cover template before publication. No automatic KDP upload or Kindle claim is made. Fixed-layout Kindle export can be added behind the export interface later.

The default font is DejaVu Sans when available, otherwise bundled Bitstream Vera. Set `BOOK_FONT_PATH` to a properly licensed Unicode TTF for your output language. Unsupported glyphs cause QA warnings. Complex-script shaping is not implemented; those languages require a shaping-capable typesetter before publication.

## Architecture and persistence

```text
Next.js studio → same-origin streaming API proxy → FastAPI
                                                   ├─ SQLAlchemy / Alembic → PostgreSQL (or local SQLite)
                                                   ├─ content-addressed storage → S3, Azure Blob, or local files
                                                   └─ database / Redis RQ / Azure Queue → workers → LangGraph
                                                                                     ├─ persisted checkpoints
                                                                                     ├─ structured OpenAI analysis
                                                                                     ├─ reference-based image generation
                                                                                     └─ ReportLab / PyMuPDF exports
```

Workflow order is `ingest_source → detect_chapters → summarize_chapters → analyze_full_story → extract_characters → generate_character_bible → generate_character_references → plan_pages → generate_page_scripts → generate_page_art → compose_pages → quality_assurance → export_pdf`.

All requested entities have relational tables, foreign keys, timestamps, and appropriate lookup/uniqueness constraints: User, BookProject, SourceDocument, Chapter, ChapterSummary, Character, CharacterReference, Location, StylePreset, Page, PagePanel, PageScript, PageArtwork, PageLayoutElement, GenerationJob, GenerationArtifact, WorkflowCheckpoint, UsageRecord, Export, QualityReport. Prompt versions, editor revisions, and immutable reference/art versions are stored. LangGraph’s SQLite/PostgreSQL checkpointer tables retain graph execution state separately from the domain checkpoints. The initial Alembic migration is an explicit immutable schema snapshot.

`DATABASE_URL` accepts SQLAlchemy PostgreSQL URLs; `CHECKPOINT_URL` accepts native psycopg PostgreSQL connection strings. Run `alembic upgrade head` before API or worker startup. Local workers poll durable database jobs; Compose workers use Redis RQ with database-authoritative redispatch. Azure uses Storage Queue, one-shot Container Apps Jobs, and scheduled recovery, so idle worker services are unnecessary. PostgreSQL advisory locks (or local file locks) prevent concurrent work on a project. Scale Redis workers across processes for independent projects. Keep SQLite to a single local worker.

For S3, set `STORAGE_BACKEND=s3`, `S3_BUCKET`, `S3_REGION`, and optionally `S3_ENDPOINT_URL`. Use the standard AWS credential chain or workload identity. Provision the bucket first and grant only necessary object read/write permissions. Storage keys are content-addressed, scoped to project IDs, and never derived from uploaded filenames. The S3 adapter is covered by a mocked transport contract test; an external bucket was not provisioned during implementation.

## Security and operations

Passwords are Argon2-hashed. Sessions use signed expiring JWTs in HTTP-only, SameSite=strict cookies. Set `SECURE_COOKIES=true`, configure a persistent strong `JWT_SECRET`, use HTTPS, and restrict `ALLOWED_ORIGINS` in deployment. Every project, artifact, generation, and download endpoint verifies ownership. Redis-backed shared rate limits fail closed if Redis is unavailable; local mode uses process-local limits. Deploy behind a trusted reverse proxy with appropriate request-size/time limits. The current login rate limiter groups requests by the API peer address, so configure proxy topology and limits for your expected traffic.

URL import accepts HTTP(S) on ports 80/443, rejects embedded credentials and all non-global resolved addresses, revalidates redirects, and pins each connection to its validated IP while preserving TLS hostname verification. It rejects compressed, binary, oversized, and non-text responses. For this reason it requires public DNS and direct public HTTP(S) routing: an egress-proxy-only runtime without public DNS must use TXT uploads or supply a trusted ingestion service with equivalent destination validation. No insecure proxy fallback is used. Private-network sources are intentionally unsupported.

Manuscript bodies and credentials are not intentionally logged. Worker error messages omit provider response bodies. SSE carries current job state with authenticated project access. API/worker deployment logs identify job IDs and failure types. Back up the relational database, graph checkpoints, and object storage together; a snapshot of live processes is not a backup. Migrations and startup do not delete retained data.

## Tests and validation

```bash
bash scripts/check.sh
# With API, worker, and web running, and a local Chromium installation:
cd frontend
CHROMIUM_PATH=/usr/bin/chromium npm run test:e2e
```

Unit/integration tests never call the paid API. They cover ingestion/encoding/chapter detection, SSRF, ownership, reference-image file routing, bounded references, Pydantic structured output integration, hierarchical event retention, budget reservations, uncertain outcomes, retry handling, cancellation/recovery, graphic panels, canonical locking, S3 object contracts, font embedding, bleed/dimensions, cover spine, QA, ZIP contents, and retained state across new sessions. The Playwright test drives the browser through an entire offline edition and checks desktop/mobile layouts and browser errors.

Optional actual PostgreSQL/Redis validation uses `tests/runtime_validation.py`: against **disposable** services, set `DATABASE_URL`, `CHECKPOINT_URL`, `REDIS_URL`, `DATA_DIR`, and `VALIDATE_DISPOSABLE_RUNTIME=1`, migrate, then run `.venv/bin/python -m tests.runtime_validation`. It delivers an actual RQ job and verifies persistent checkpoints at a human review gate. Do not run against production services.

## Current verification

The implementation was exercised with 42 passing backend tests, successful Next.js type checking/production builds, passing Chromium acceptance tests in local mode and the complete Docker Compose stack, actual PostgreSQL/Redis RQ delivery/checkpoint persistence, and the 1.1-million-character Gutenberg Ivanhoe source (44 numbered chapters plus opening material). The Azure deployment also passed the full hosted browser workflow against real PostgreSQL, managed-identity Blob Storage, and queue-triggered container jobs. Paid generation and live S3 were not exercised. Direct source URL ingestion was blocked by this cloud runtime’s public-DNS restriction; TXT ingestion and authenticated Git retrieval of the public-domain source were verified. Docker packaging verification is documented in `VALIDATION.md`.
