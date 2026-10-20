"""Run one queue delivery per Container Apps Job, or periodically repair dispatch."""

import argparse
import json
import logging
from threading import Event, Thread

from sqlalchemy import select

from .azure_queue import queue_client
from .db import SessionLocal
from .models import GenerationJob
from .worker import enqueue, execute, recover_stale

logger = logging.getLogger("alexandria.azure_worker")


def recover():
    recover_stale()
    with SessionLocal() as db:
        ids = list(db.scalars(select(GenerationJob.id).where(GenerationJob.status == "queued").limit(500)))
    for job_id in ids:
        enqueue(job_id)


def consume_one():
    with queue_client() as queue:
        message = next(iter(queue.receive_messages(messages_per_page=1, visibility_timeout=300)), None)
        if message is None:
            return
        try:
            job_id = json.loads(message.content)["job_id"]
            if not isinstance(job_id, str) or not job_id or len(job_id) > 100:
                raise ValueError("Invalid job ID")
        except (ValueError, KeyError, TypeError):
            logger.warning("invalid_queue_message")
            queue.delete_message(message)
            return
        stopped = Event()
        receipt = [message.pop_receipt]

        def renew():
            while not stopped.wait(60):
                try:
                    update = queue.update_message(message.id, receipt[0], visibility_timeout=300)
                    receipt[0] = update.pop_receipt
                except Exception:
                    # Project advisory locks protect against duplicate execution after lease expiry.
                    logger.warning("queue_lease_renewal_failed", extra={"job_id": job_id})
                    return

        keeper = Thread(target=renew, daemon=True)
        keeper.start()
        completed = False
        try:
            execute(job_id)
            completed = True  # Domain failure/review/cancel states are persisted by execute().
        finally:
            stopped.set()
            keeper.join(timeout=65)
        if completed:
            queue.delete_message(message.id, receipt[0])


def main():
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--recover", action="store_true")
    args = parser.parse_args()
    if args.recover:
        recover()
    else:
        consume_one()


if __name__ == "__main__":
    main()
