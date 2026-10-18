"""RQ-backed durable dispatch; SQLite database queue is available for single-worker local development."""

import logging
import time
from contextlib import contextmanager
from datetime import timedelta

from sqlalchemy import select, text

from .config import settings
from .db import SessionLocal, engine, now
from .models import BookProject, Character, GenerationJob, Page, PageArtwork, PageScript
from .workflow import JobStopped, ReviewRequired, Workflow, run_graph

logger = logging.getLogger("alexandria.worker")


@contextmanager
def project_lock(project_id):
    # Holds a session-scoped advisory lock for PG, a process-safe OS file lock for local mode.
    if settings().database_url.startswith("postgresql"):
        with engine.connect() as lock_db:
            locked = lock_db.execute(
                text("SELECT pg_try_advisory_lock(hashtext(:id))"), {"id": project_id}
            ).scalar()
            lock_db.commit()
            if not locked:
                yield False
                return
            try:
                yield True
            finally:
                lock_db.execute(text("SELECT pg_advisory_unlock(hashtext(:id))"), {"id": project_id})
                lock_db.commit()
    else:
        import fcntl

        with open(settings().data_dir / f"lock-{project_id}", "a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def execute(job_id):
    with SessionLocal() as db:
        job = db.get(GenerationJob, job_id)
        if not job or job.status != "queued":
            return
        with project_lock(job.project_id) as acquired:
            if not acquired:
                return
            db.refresh(job)
            if job.status != "queued":
                return
            job.status = "running"
            job.attempts += 1
            job.error = None
            job.heartbeat = now()
            db.commit()
            try:
                if job.kind == "workflow":
                    run_graph(db, job)
                else:
                    flow = Workflow(db, job)
                    flow.guard()
                    if job.kind == "portrait":
                        flow.portrait(db.get(Character, job.target_id))
                    elif job.kind == "page_art":
                        page = db.get(Page, job.target_id)
                        flow.page_art(page)
                        flow.compose_page(page)
                    elif job.kind == "cover":
                        flow.cover_art()
                    elif job.kind == "page_qa":
                        page = db.get(Page, job.target_id)
                        artwork = db.get(PageArtwork, page.current_artwork_id)
                        script = db.scalar(select(PageScript).where(PageScript.page_id == page.id))
                        references, _ = flow.references(script.data)
                        qa = flow.ai.visual_qa(flow.storage.get(artwork.storage_key), references, script.data)
                        artwork.metadata_json = {
                            **artwork.metadata_json,
                            "qa_reference_ids": [name for name, _ in references],
                        }
                        flow.record("visual_qa", artwork.id, qa.model_dump())
                    else:
                        raise ValueError("Unsupported job type")
                job.status = "completed"
                job.progress = 100
                if job.kind == "workflow":
                    db.get(BookProject, job.project_id).status = "completed"
            except ReviewRequired as exc:
                job.status = "review"
                job.error = str(exc)
            except JobStopped:
                db.refresh(job)
                job.status = "cancelled" if job.control == "cancel" else "paused"
            except Exception as exc:
                db.rollback()
                job = db.get(GenerationJob, job_id)
                job.status = "failed"
                # Deliberately omit provider response bodies, credentials and manuscript text.
                job.error = (
                    str(exc)[:400]
                    if isinstance(exc, ValueError)
                    else f"{type(exc).__name__}: operation failed; inspect service connectivity and usage reservations"
                )
                logger.warning("job_failed", extra={"job_id": job_id, "error_type": type(exc).__name__})
            job.heartbeat = now()
            db.commit()


def enqueue(job_id):
    if settings().redis_url:
        from redis import Redis
        from rq import Queue

        Queue("alexandria", connection=Redis.from_url(settings().redis_url)).enqueue(
            execute,
            job_id,
            job_id=f"dispatch-{job_id}-{time.time_ns()}",
            job_timeout=86400,
            result_ttl=3600,
            failure_ttl=86400,
        )


def recover_stale():
    with SessionLocal() as db:
        stale = list(
            db.scalars(
                select(GenerationJob).where(
                    GenerationJob.status == "running", GenerationJob.heartbeat < now() - timedelta(minutes=10)
                )
            )
        )
        for job in stale:
            with project_lock(job.project_id) as acquired:
                if acquired:
                    job.status = "failed"
                    job.error = "Worker stopped. Retry resumes saved work; reconcile any uncertain API reservations first."
        db.commit()


def main():
    logging.basicConfig(level=settings().log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if settings().redis_url:
        # Supervisor keeps database-authoritative queued jobs dispatched after Redis/container restarts.
        from multiprocessing import Process

        from redis import Redis
        from rq import Worker

        def consume():
            Worker(["alexandria"], connection=Redis.from_url(settings().redis_url)).work()

        process = Process(target=consume)
        process.start()
        try:
            while process.is_alive():
                recover_stale()
                with SessionLocal() as db:
                    for job in db.scalars(select(GenerationJob).where(GenerationJob.status == "queued")):
                        enqueue(job.id)
                time.sleep(15)
        finally:
            process.terminate()
            process.join()
    else:
        while True:
            recover_stale()
            with SessionLocal() as db:
                ids = list(
                    db.scalars(
                        select(GenerationJob.id)
                        .where(GenerationJob.status == "queued")
                        .order_by(GenerationJob.created_at)
                    )
                )
            for job_id in ids:
                execute(job_id)
            time.sleep(1)


if __name__ == "__main__":
    main()
