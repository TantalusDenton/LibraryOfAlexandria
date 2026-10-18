# Validation record

- Backend: 33 automated tests passed with offline and mocked OpenAI/S3 adapters. No paid API calls.
- Relational schema: initial migration applied; `alembic check` reports no pending schema operations.
- Frontend: Next.js production build and TypeScript checks passed.
- Browser: Chromium completed account creation, TXT import, analysis, approvals, two canonical references, two generated pages, page editor, cover generation, PDF/ZIP export, reload persistence, and a 390px mobile layout without browser errors or horizontal overflow.
- PostgreSQL 17 + Redis 7: actual RQ delivery, PostgreSQL LangGraph checkpoint tables, six completed domain stages, and the first review gate verified.
- Docker: both production images built with frozen dependency installation and verified TLS. The complete Compose stack passed the same browser acceptance workflow from a fresh disposable PostgreSQL database, including an active SSE stream during initial checkpoint creation.
- Long manuscript: Gutenberg Ivanhoe #82, 1,107,626 normalized characters; 44 numbered chapters plus opening material detected.
- Export: interior/cover geometry, font embedding, low-DPI warnings, source-event coverage, offline proof labeling, page count, spine calculation, and ZIP contents checked.
- Additional contracts: strict OpenAI JSON schemas, refusing reference-less fallback when inputs cannot fit, reusing completed art after a QA failure, global style image inputs, and a 100-chapter paginated contents plan.
- Not exercised: live OpenAI image/model availability and billing; live S3 service; KDP acceptance/publication.

Build containers initially failed to resolve public package hosts and the supplied egress-proxy hostname. Supplying the existing proxy hostname mapping and its trusted CA fixed the builds while preserving TLS verification. `scripts/cloud_build.py` reproduces this procedure. Direct source URL ingestion still needs public DNS/direct routing; the cloud-only proxy does not supply that capability.
