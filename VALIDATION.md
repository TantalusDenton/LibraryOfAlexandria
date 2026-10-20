# Validation record

- Backend: 42 automated tests passed with offline and mocked OpenAI/S3/Azure adapters. No paid API calls.
- Relational schema: initial migration applied; `alembic check` reports no pending schema operations.
- Frontend: Next.js production build and TypeScript checks passed.
- Browser: Chromium completed account creation, TXT import, analysis, approvals, two canonical references, two generated pages, page editor, cover generation, PDF/ZIP export, reload persistence, and a 390px mobile layout without browser errors or horizontal overflow.
- PostgreSQL 17 + Redis 7: actual RQ delivery, PostgreSQL LangGraph checkpoint tables, six completed domain stages, and the first review gate verified.
- Docker: both production images built with frozen dependency installation and verified TLS. The complete Compose stack passed the same browser acceptance workflow from a fresh disposable PostgreSQL database, including an active SSE stream during initial checkpoint creation.
- Long manuscript: Gutenberg Ivanhoe #82, 1,107,626 normalized characters; 44 numbered chapters plus opening material detected.
- Export: interior/cover geometry, font embedding, low-DPI warnings, source-event coverage, offline proof labeling, page count, spine calculation, and ZIP contents checked.
- Additional contracts: strict OpenAI JSON schemas, refusing reference-less fallback when inputs cannot fit, reusing completed art after a QA failure, global style image inputs, and a 100-chapter paginated contents plan.
- Not exercised: live OpenAI image/model availability and billing; live S3 service; KDP acceptance/publication.

Azure is deployed in West US 2 with private PostgreSQL 16 (`Standard_B2s`, 32 GiB, seven-day backups), managed-identity Blob/Queue storage, Key Vault secrets, owner-account bootstrap, disabled public signup, and zero-to-two app replicas/worker executions. Four infrastructure tests passed. Both production images built and pushed through ACR Tasks using the compatible `Dockerfile.acr` files. The hosted Chromium workflow passed in 4.4 minutes: existing-owner login, delayed TXT upload, automatic queue workers, persisted review gates, canonical references, page art, cover, PDF/ZIP downloads, reload persistence, and mobile layout. All six worker executions succeeded. No paid model calls were made.

Hosted testing found and fixed an upload timing bug: opening a project before source upload completed could retain an empty manuscript view. The browser regression deliberately delays the upload and passes locally and on Azure. Explicit session-key version pinning and a new revision invalidate old sessions; rejection of a retired session was verified with HTTP 401. Hosted diagnostic output redacts passwords and session tokens. HTTPS verification remained enabled; Chromium required writable access to its existing NSS trust database to load this environment's proxy CA.

East US 2 rejected the small PostgreSQL SKUs. The failed, empty resource group was fully removed after moving to West US 2. The resource-group budget is $75/month with approximate $50/$75/$100 actual-spend notifications; alerts do not cap spending.

Azure idle verification observed zero application replicas. A subsequent HTTPS `/api/health` request automatically woke the application and returned 200 in 30.41 seconds. Public signup was separately verified to return 403. Cold-start latency is an observed sample, not a response-time guarantee.

Build containers initially failed to resolve public package hosts and the supplied egress-proxy hostname. Supplying the existing proxy hostname mapping and its trusted CA fixed the builds while preserving TLS verification. `scripts/cloud_build.py` reproduces this procedure. Direct source URL ingestion still needs public DNS/direct routing; the cloud-only proxy does not supply that capability.
