"""Turning ingestion work into durable jobs, and running them off the queue.

Two things have to hold once work stops being a live Python object: the event
must survive JSON intact, and a multi-megabyte file must not be shoved through
Redis. And the worker has to treat a failing job as retryable rather than
printing the error and moving on, which is what lost documents before.
"""
import asyncio
from datetime import datetime, timezone

import pytest

from module_1_document_processing.composio_connector.events.canonical_event import (
    CanonicalEvent,
    EventType,
)
from module_1_document_processing.pipeline import job_payloads
from module_1_document_processing.pipeline.durable_queue import DurableQueue
from module_1_document_processing.pipeline.job_payloads import (
    JOB_CONNECTOR_EVENT,
    event_to_payload,
    payload_to_event,
)
from module_1_document_processing.pipeline.queue_worker import QueueWorker
from tests.fake_redis import FakeRedis


class FakeObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, data: bytes, content_type: str = "") -> str:
        self.objects[key] = data
        return f"fake://{key}"

    def get(self, ref: str):
        return self.objects.get(ref.replace("fake://", ""))

    def delete(self, ref: str) -> None:
        self.objects.pop(ref.replace("fake://", ""), None)


@pytest.fixture
def object_store(monkeypatch) -> FakeObjectStore:
    store = FakeObjectStore()
    monkeypatch.setattr(job_payloads, "raw_object_store", store)
    return store


def make_event(**overrides) -> CanonicalEvent:
    defaults = dict(
        event_id="evt_1",
        event_type=EventType.UPDATE,
        source="gdrive",
        tenant_id="tenant_a",
        user_id="user_1",
        external_id="file_99",
        raw_ref={"fileId": "file_99"},
        acl=["user:user_1", "tenant:tenant_a"],
        timestamp=datetime(2026, 9, 12, 10, 30, tzinfo=timezone.utc),
        metadata={"name": "pricing.pdf", "mime_type": "application/pdf"},
    )
    defaults.update(overrides)
    return CanonicalEvent(**defaults)


# --- payload codec --------------------------------------------------------
def test_event_survives_the_queue_intact(object_store):
    restored = payload_to_event(event_to_payload(make_event()))
    original = make_event()

    assert restored.event_id == original.event_id
    assert restored.event_type is EventType.UPDATE  # enum, not a bare string
    assert restored.source == original.source
    assert restored.tenant_id == original.tenant_id
    assert restored.external_id == original.external_id
    assert restored.acl == original.acl
    assert restored.raw_ref == original.raw_ref
    assert restored.timestamp == original.timestamp
    assert restored.metadata["name"] == "pricing.pdf"


def test_payload_is_json_serializable(object_store):
    import json

    json.dumps(event_to_payload(make_event()))  # must not raise


def test_file_bytes_are_offloaded_not_queued(object_store):
    """A 25MB upload must not travel through Redis - and staging the bytes is
    also what makes the accepted upload durable."""
    blob = b"%PDF-1.7" + b"x" * 50_000
    payload = event_to_payload(make_event(metadata={"name": "big.pdf", "mime_type": "application/pdf", "raw_bytes": blob}))

    assert "raw_bytes" not in payload["metadata"]
    assert payload["staged_ref"]
    assert object_store.objects  # the bytes went to the object store

    restored = payload_to_event(payload)
    assert restored.metadata["raw_bytes"] == blob


def test_missing_staged_bytes_do_not_crash_the_job(object_store):
    payload = event_to_payload(make_event(metadata={"name": "x.pdf", "raw_bytes": b"data"}))
    object_store.objects.clear()  # object store lost it

    restored = payload_to_event(payload)
    assert "raw_bytes" not in restored.metadata
    assert restored.event_id == "evt_1"


def test_unknown_event_type_falls_back_to_create(object_store):
    payload = event_to_payload(make_event())
    payload["event_type"] = "NONSENSE"
    assert payload_to_event(payload).event_type is EventType.CREATE


# --- worker loop ----------------------------------------------------------
def build_worker(queue: DurableQueue) -> QueueWorker:
    stub = object()
    return QueueWorker(
        scanner=stub, store=stub, parser_service=stub, deletion_handler=stub,
        acl_sync=stub, gatekeeper_engine=stub, ingestion_pipeline=stub, queue=queue,
    )


def run(coro):
    return asyncio.run(coro)


def test_worker_runs_a_registered_handler_and_acks():
    store = FakeRedis()
    queue = DurableQueue(name="t:q", client=store, consumer_id="w1", max_attempts=3)
    worker = build_worker(queue)
    seen: list[dict] = []
    worker.register_handler("thing", lambda payload: seen.append(payload))

    async def scenario():
        await worker.start()
        await worker.enqueue_job("thing", {"doc_id": "doc_1", "tenant_id": "tenant_a"})
        await asyncio.sleep(0.3)
        await worker.stop()

    run(scenario())

    assert seen == [{"doc_id": "doc_1", "tenant_id": "tenant_a"}]
    assert store.llen(queue.pending_key) == 0
    assert store.llen(queue.inflight_key()) == 0  # acked, not left hanging


def test_a_failing_job_is_retried_not_dropped():
    store = FakeRedis()
    queue = DurableQueue(name="t:q", client=store, consumer_id="w1", max_attempts=3, backoff_seconds=60)
    worker = build_worker(queue)

    def explode(payload):
        raise RuntimeError("embedding service is down")

    worker.register_handler("thing", explode)

    async def scenario():
        await worker.start()
        await worker.enqueue_job("thing", {"doc_id": "doc_1", "tenant_id": "tenant_a"})
        await asyncio.sleep(0.3)
        await worker.stop()

    run(scenario())

    # Held for a backed-off retry rather than lost, and not still in flight.
    assert store.zcard(queue.retry_key) == 1
    assert store.llen(queue.inflight_key()) == 0
    assert store.llen(queue.dead_key) == 0


def test_a_job_with_no_handler_is_not_silently_discarded():
    store = FakeRedis()
    queue = DurableQueue(name="t:q", client=store, consumer_id="w1", max_attempts=1)
    worker = build_worker(queue)

    async def scenario():
        await worker.start()
        await worker.enqueue_job("nobody_handles_this", {"doc_id": "doc_1", "tenant_id": "tenant_a"})
        await asyncio.sleep(0.3)
        await worker.stop()

    run(scenario())

    dead = queue.dead_letters()
    assert len(dead) == 1
    assert "No handler registered" in dead[0]["last_error"]


def test_startup_reclaims_work_abandoned_by_a_previous_run():
    """The restart case: a job left in flight must be picked back up."""
    store = FakeRedis()
    crashed = DurableQueue(name="t:q", client=store, consumer_id="w-old", max_attempts=3)
    crashed.enqueue("thing", {"doc_id": "doc_1", "tenant_id": "tenant_a"})
    crashed.reserve()
    store.expire_heartbeat(crashed.heartbeat_key())

    queue = DurableQueue(name="t:q", client=store, consumer_id="w-new", max_attempts=3)
    worker = build_worker(queue)
    seen: list[dict] = []
    worker.register_handler("thing", lambda payload: seen.append(payload))

    async def scenario():
        await worker.start()
        await asyncio.sleep(0.3)
        await worker.stop()

    run(scenario())

    assert [p["doc_id"] for p in seen] == ["doc_1"]


def test_connector_events_are_enqueued_as_jobs(object_store):
    store = FakeRedis()
    queue = DurableQueue(name="t:q", client=store, consumer_id="w1")
    worker = build_worker(queue)

    job = run(worker.enqueue(make_event()))

    assert job.kind == JOB_CONNECTOR_EVENT
    assert job.payload["external_id"] == "file_99"
    assert store.llen(queue.pending_key) == 1
