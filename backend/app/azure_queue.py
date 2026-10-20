"""Keyless Azure Storage clients; queue messages contain IDs, never manuscript text."""

import json

from .config import settings


def credential():
    from azure.identity import DefaultAzureCredential, ManagedIdentityCredential

    if settings().azure_client_id:
        return ManagedIdentityCredential(client_id=settings().azure_client_id)
    return DefaultAzureCredential()


def queue_client():
    from azure.storage.queue import QueueClient

    return QueueClient.from_queue_url(settings().azure_queue_url, credential=credential())


def enqueue_job(job_id):
    with queue_client() as queue:
        queue.send_message(json.dumps({"job_id": job_id}), time_to_live=7 * 86400)
