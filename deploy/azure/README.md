# Azure MVP deployment

This deploys the studio to Azure Container Apps Consumption with HTTPS and zero minimum replicas. Next.js and FastAPI share one app replica and communicate over localhost; only the frontend port is exposed. Up to two event-driven container jobs process Azure Storage Queue deliveries. A short recovery job runs every five minutes, repairs failed dispatch, and marks abandoned work for explicit retry. It does not automatically retry uncertain paid calls.

Persistent state lives in private-network PostgreSQL Flexible Server and private, versioned Blob Storage. The deployment uses a user-assigned managed identity for storage, registry pulls, and Key Vault references, without storage keys or registry admin passwords. It provisions a Consumption-only environment, no load balancer, NAT gateway, dedicated worker, or Redis. PostgreSQL, the registry, logs, storage, networking usage, and optional remote image builds have costs even when the app is idle.

## Deploy

Use Azure Cloud Shell (Bash), or a machine with Python 3.12+ and Azure CLI. The default builds images remotely with ACR Tasks and the compatible `Dockerfile.acr` in each context, so Docker is not required. The regular Dockerfiles support an optional BuildKit CA secret for proxied local builds. Some trial subscriptions restrict ACR Tasks; use `--build-method local` on a Docker-capable machine in that case. Deploy from a complete checkout or deployment ZIP that includes these Azure files.

```bash
az login --use-device-code
az account list --output table
python deploy/azure/deploy.py \
  --subscription YOUR_SUBSCRIPTION_ID \
  --owner-email YOUR_EMAIL \
  --location westus2
```

The account needs permission to create resources and role assignments, such as Owner on the selected subscription. Existing Azure credits apply according to subscription terms. Microsoft sign-in must be completed interactively; an email address alone does not grant Azure access. Never send a password or Azure access token in chat.

The defaults are resource group `alexandria-mvp-westus2`, West US 2, PostgreSQL 16 on `Standard_B2s` with 32 GiB storage and seven-day backups, zero-to-two application replicas, and zero-to-two worker executions. The smaller `Standard_B1ms` can be requested explicitly where available; Azure rejected both small sizes during initial provisioning in East US 2. Actual region/SKU availability and resource-policy compatibility are checked by Azure during deployment.

Generated database, session, and initial owner passwords are retained in `.cache/azure/<suffix>/parameters.json` with mode 0600 and submitted as secure ARM parameters. Keep a secure copy for repeat deployments. The script refuses to regenerate credentials for an existing resource group when that private file is missing. Do not commit `.cache/`, publish parameter files, or delete the database to fix a deployment failure. Repeat the same command to continue an interrupted deployment; migrations are idempotent, and bootstrap never resets an existing owner's password. Retain the same owner email on updates.

Deployment creates the foundation, builds immutable image tags, runs and checks a separate migration/bootstrap job, and then rolls out application/worker resources. It checks the public HTTPS frontend, database-backed `/api/health`, and unauthenticated-account denial. If a phase fails, previously created resources remain and can incur charges. Azure CLI error details are saved privately in `.cache/azure/last-error.txt`. First-time role propagation can require several minutes before keyless image pulls and Key Vault references work; inspect the failed execution before retrying.

## First login and live AI

Public registration is disabled. An initial account is created for `--owner-email`. Its random password is held in the deployment Key Vault as `owner-password`; retrieve it securely in Azure Portal. The script grants the signed-in operator the **Key Vault Secrets User** role on this vault. It identifies the operator from the authenticated CLI token without logging or retaining that token. The same initial password is also in the protected local deployment parameter file. The studio account is separate from Microsoft sign-in.

AI is deployed in **offline mode** with no OpenAI key. No paid model calls are made by the deploy or health checks. Enabling live AI is a separate configuration change: store the key in Key Vault, add a secret reference to both API and worker jobs, set live mode, confirm current pricing and conservative charge reservations, and keep project budgets and concurrency caps. Never give the frontend container the OpenAI key. Any live smoke test requires explicit spending authorization.

The resource-group budget is $75/month, with actual-spend email alerts at approximately $50, $75, and $100. Alerts do not cap or stop spending. The Log Analytics workspace has a 0.1 GB/day ingestion cap; this can delay or drop logs after the cap. Cold starts and the 30-second queue poll add startup latency. The two-replica API has per-replica login limits in this Redis-free MVP; use an edge/shared limiter before wider public signup.

## Verify and operate

For automated hosted verification on a machine with the frontend test dependencies and Chromium installed, run `python deploy/azure/smoke.py .cache/azure/<suffix>/deployment.json`. It retrieves the owner password directly into process memory, requires offline AI mode before any generation, and redacts session cookies from diagnostic output. It creates a clearly named deployment proof project. In a sandbox that makes the browser's NSS certificate database read-only, the browser needs narrowly approved access to that existing database to initialize its trusted CA store; keep HTTPS verification enabled.

Session signing keys are pinned to an explicit Key Vault version. To rotate sessions, update `sessionKey` in the protected parameter file and redeploy. The version change creates a fresh application revision even when image tags are reused, invalidating existing sessions when the new revision takes traffic. Keep the initial owner password and database credentials unchanged when performing this operation.

After deployment, log in and create a short rights-cleared offline manuscript. Verify that the queued workflow starts, pauses at review, and remains after refresh. Upload/download an image and export a PDF to exercise Blob Storage. Check that worker executions terminate at completion and the application replica count falls to zero after idle cooldown. These hosted checks require Azure access; local adapter tests cannot prove managed-identity RBAC, private DNS, quota availability, or scale behavior.

App rollouts use one active revision and may interrupt requests. Background jobs retain database checkpoints; database advisory locks prevent simultaneous execution of the same project. Queue visibility is renewed during long jobs; duplicate deliveries are safe to ignore once domain work has advanced. An abrupt worker termination leaves running work for recovery and explicit retry. PostgreSQL backups and Blob versioning provide recovery; perform an actual restoration exercise before relying on them for production.

For rollback, deploy the previous image tag using `runtime()` and the same resource names. Confirm migration compatibility first; rolling back containers does not undo database migrations. To suspend app compute, stop event triggers and app traffic; PostgreSQL continues to have costs. Resource-group deletion destroys database and storage resources and is intentionally not automated by this script.

## Local validation

```bash
python deploy/azure/deploy.py --render-only --owner-email owner@example.org
python -m unittest discover -s deploy/azure -p 'test_*.py' -v
cd backend
.venv/bin/ruff check app tests
.venv/bin/pytest -q
```

Render mode creates no resources and performs no Azure requests. ARM template validation, deployment, identity permissions, DNS, HTTPS, and actual scaling remain unverified until run against an authenticated Azure subscription.
