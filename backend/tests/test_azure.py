import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import azure_queue, azure_worker
from app.config import settings
from app.main import app, windows
from app.models import GenerationJob
from app.storage import Storage
from app.worker import enqueue
from tests.helpers import make_project


def test_blob_storage_is_private_immutable_and_maps_missing_objects(monkeypatch):
    from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
    from azure.storage.blob import BlobServiceClient

    objects = {}

    class Container:
        def upload_blob(self, key, value, **kwargs):
            assert kwargs["overwrite"] is False
            assert kwargs["content_settings"].content_type == "text/plain"
            if key in objects:
                raise ResourceExistsError("already present")
            objects[key] = value

        def download_blob(self, key):
            if key not in objects:
                raise ResourceNotFoundError("missing")
            return SimpleNamespace(readall=lambda: objects[key])

    def service(**kwargs):
        assert kwargs == {"account_url": "https://test.blob.core.windows.net", "credential": "identity"}
        return SimpleNamespace(get_container_client=lambda name: Container() if name == "objects" else None)

    monkeypatch.setattr(settings(), "storage_backend", "azure")
    monkeypatch.setattr(settings(), "azure_storage_account_url", "https://test.blob.core.windows.net")
    monkeypatch.setattr(azure_queue, "credential", lambda: "identity")
    monkeypatch.setattr("azure.storage.blob.BlobServiceClient", service)
    assert BlobServiceClient is not None
    store = Storage()
    key = store.put("project", b"manuscript", "txt", "text/plain")
    assert store.put("project", b"manuscript", "txt", "text/plain") == key
    assert store.get(key) == b"manuscript"
    with pytest.raises(FileNotFoundError):
        store.get("project/missing.txt")
    with pytest.raises(ValueError):
        store.get("../private")


class Queue:
    def __init__(self, messages=()):
        self.messages = messages
        self.sent = []
        self.deleted = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def send_message(self, content, **kwargs):
        self.sent.append((json.loads(content), kwargs))

    def receive_messages(self, **kwargs):
        assert kwargs == {"messages_per_page": 1, "visibility_timeout": 300}
        return iter(self.messages)

    def delete_message(self, *args):
        self.deleted.append(args)


def test_queue_dispatch_contains_only_the_durable_job_id(monkeypatch):
    queue = Queue()
    monkeypatch.setattr(settings(), "azure_queue_url", "https://test.queue.core.windows.net/generation")
    monkeypatch.setattr(azure_queue, "queue_client", lambda: queue)
    enqueue("job-123")
    assert queue.sent == [({"job_id": "job-123"}, {"time_to_live": 604800})]


def test_one_shot_worker_persists_review_and_ignores_duplicate_deliveries(db, monkeypatch):
    project, job = make_project(db)
    job.status = "queued"
    db.commit()
    message = SimpleNamespace(id="message", pop_receipt="receipt", content=json.dumps({"job_id": job.id}))
    queue = Queue([message])
    monkeypatch.setattr(azure_worker, "queue_client", lambda: queue)
    azure_worker.consume_one()
    db.refresh(job)
    assert job.status == "review"
    attempts = job.attempts
    azure_worker.consume_one()
    db.refresh(job)
    assert job.attempts == attempts
    assert queue.deleted == [("message", "receipt")] * 2


def test_uncaught_worker_failure_leaves_message_for_redelivery(monkeypatch):
    queue = Queue([SimpleNamespace(id="message", pop_receipt="receipt", content='{"job_id":"job"}')])
    monkeypatch.setattr(azure_worker, "queue_client", lambda: queue)

    def disconnected(job_id):
        raise ConnectionError("database unavailable")

    monkeypatch.setattr(azure_worker, "execute", disconnected)
    with pytest.raises(ConnectionError):
        azure_worker.consume_one()
    assert not queue.deleted


def test_recovery_redispatches_only_queued_work(db, monkeypatch):
    project, job = make_project(db)
    job.status = "queued"
    db.add(GenerationJob(project_id=project.id, status="review"))
    db.commit()
    sent = []
    monkeypatch.setattr(azure_worker, "enqueue", sent.append)
    azure_worker.recover()
    assert sent == [job.id]


def test_deployed_signup_can_be_disabled_without_affecting_login(monkeypatch):
    windows.clear()
    with TestClient(app) as client:
        account = {"email": "owner@example.org", "password": "a-secure-test-password"}
        assert client.post("/auth/register", json=account).status_code == 201
        client.post("/auth/logout")
        monkeypatch.setattr(settings(), "registration_enabled", False)
        assert client.post("/auth/register", json=account).status_code == 403
        assert client.post("/auth/login", json=account).status_code == 200


def test_managed_identity_does_not_require_storage_keys(monkeypatch):
    monkeypatch.setattr(settings(), "azure_client_id", "studio-client")
    seen = []
    monkeypatch.setattr("azure.identity.ManagedIdentityCredential", lambda **kwargs: seen.append(kwargs))
    azure_queue.credential()
    assert seen == [{"client_id": "studio-client"}]


def test_queue_renewal_deletes_with_the_new_receipt(monkeypatch):
    queue = Queue([SimpleNamespace(id="message", pop_receipt="old", content='{"job_id":"job"}')])
    calls = []

    def update(message_id, receipt, **kwargs):
        calls.append((message_id, receipt, kwargs))
        return SimpleNamespace(pop_receipt="renewed")

    class Tick:
        def __init__(self):
            self.ticks = 0

        def wait(self, seconds):
            self.ticks += 1
            return self.ticks > 1

        def set(self):
            pass

    class Thread:
        def __init__(self, target, **kwargs):
            self.target = target

        def start(self):
            self.target()

        def join(self, **kwargs):
            pass

    queue.update_message = update
    monkeypatch.setattr(azure_worker, "queue_client", lambda: queue)
    monkeypatch.setattr(azure_worker, "Thread", Thread)
    monkeypatch.setattr(azure_worker, "Event", Tick)
    monkeypatch.setattr(azure_worker, "execute", lambda job_id: None)
    azure_worker.consume_one()
    assert calls == [("message", "old", {"visibility_timeout": 300})]
    assert queue.deleted == [("message", "renewed")]


def test_bootstrap_creates_owner_once_and_never_resets_password(db, monkeypatch):
    from sqlalchemy import select

    from app.auth import password_hasher
    from app.azure_bootstrap import main
    from app.models import User

    monkeypatch.setenv("OWNER_EMAIL", "owner@example.org")
    monkeypatch.setenv("OWNER_PASSWORD", "first-long-owner-password")
    main()
    monkeypatch.setenv("OWNER_PASSWORD", "second-long-owner-password")
    main()
    user = db.scalar(select(User).where(User.email == "owner@example.org"))
    assert password_hasher.verify("first-long-owner-password", user.password_hash)
