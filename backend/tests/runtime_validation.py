"""Opt-in actual PostgreSQL/Redis integration. Never run against a production database."""

import os
import uuid

from redis import Redis
from rq import SimpleWorker
from sqlalchemy import select

from app.db import SessionLocal
from app.models import GenerationJob, WorkflowCheckpoint
from app.worker import enqueue
from tests.helpers import make_project


def main():
    if os.environ.get("VALIDATE_DISPOSABLE_RUNTIME") != "1":
        raise SystemExit("Set VALIDATE_DISPOSABLE_RUNTIME=1 for a disposable PostgreSQL/Redis instance")
    with SessionLocal() as db:
        project, job = make_project(db, email=f"runtime-{uuid.uuid4()}@example.org")
        job_id = job.id
        enqueue(job_id)
    worker = SimpleWorker(["alexandria"], connection=Redis.from_url(os.environ["REDIS_URL"]))
    worker.work(burst=True, logging_level="WARNING")
    with SessionLocal() as db:
        job = db.get(GenerationJob, job_id)
        assert job.status == "review", (job.status, job.error)
        assert job.stage == "generate_character_references"
        count = len(
            list(db.scalars(select(WorkflowCheckpoint).where(WorkflowCheckpoint.project_id == project.id)))
        )
        assert count >= 6
        print(
            f"PostgreSQL + Redis RQ: durable job delivered, {count} stages checkpointed, review gate reached"
        )


if __name__ == "__main__":
    main()
