"""The staging queue's durability contract.

Before this, accepted ingestion work lived in an ``asyncio.Queue`` inside the
serving process: a restart silently dropped documents the API had already
promised to index, and a transient failure lost them outright. These tests pin
the properties that fix that - work survives a restart, failures retry and then
dead-letter, and a crashed consumer's in-flight job is reclaimed.
"""
import time

import pytest

from module_1_document_processing.pipeline.durable_queue import DurableQueue, Job
from tests.fake_redis import FakeRedis

TENANT = "tenant_a"
OTHER_TENANT = "tenant_b"


def make_queue(client=None, consumer_id="worker-1", **kwargs) -> DurableQueue:
    return DurableQueue(
        name="test:ingest",
        client=client if client is not None else FakeRedis(),
        consumer_id=consumer_id,
        max_attempts=kwargs.pop("max_attempts", 3),
        backoff_seconds=kwargs.pop("backoff_seconds", 10.0),
        heartbeat_seconds=kwargs.pop("heartbeat_seconds", 60),
        **kwargs,
    )


def payload(tenant_id=TENANT, doc_id="doc_1") -> dict:
    return {"doc_id": doc_id, "tenant_id": tenant_id, "filename": "x.txt"}


# --- the core contract ----------------------------------------------------
def test_queued_work_survives_a_restart():
    """The reason this queue exists: an accepted job must outlive the process."""
    store = FakeRedis()
    before = make_queue(store)
    job = before.enqueue("document_ingest", payload())

    # A new process over the same Redis - i.e. the service restarted.
    after = make_queue(store, consumer_id="worker-1")
    reserved = after.reserve()

    assert reserved is not None
    assert reserved.job_id == job.job_id
    assert reserved.payload["doc_id"] == "doc_1"


def test_reserve_holds_the_job_in_flight_until_acked():
    store = FakeRedis()
    queue = make_queue(store)
    queue.enqueue("document_ingest", payload())

    job = queue.reserve()
    assert store.llen(queue.pending_key) == 0
    assert store.llen(queue.inflight_key()) == 1  # claimed, not lost

    queue.ack(job)
    assert store.llen(queue.inflight_key()) == 0


def test_a_crashed_consumer_does_not_strand_its_job():
    store = FakeRedis()
    crashed = make_queue(store, consumer_id="worker-dead")
    crashed.enqueue("document_ingest", payload())
    crashed.reserve()
    assert store.llen(crashed.inflight_key()) == 1

    # The consumer dies: its heartbeat expires.
    store.expire_heartbeat(crashed.heartbeat_key())

    survivor = make_queue(store, consumer_id="worker-live")
    assert survivor.reclaim_stale() == 1
    assert store.llen(crashed.inflight_key()) == 0
    assert survivor.reserve().payload["doc_id"] == "doc_1"


def test_a_live_consumers_work_is_not_stolen():
    store = FakeRedis()
    busy = make_queue(store, consumer_id="worker-busy")
    busy.enqueue("document_ingest", payload())
    busy.reserve()  # beats, so it looks alive

    other = make_queue(store, consumer_id="worker-other")
    assert other.reclaim_stale() == 0
    assert store.llen(busy.inflight_key()) == 1


# --- failure handling -----------------------------------------------------
def test_failure_schedules_a_backed_off_retry():
    store = FakeRedis()
    queue = make_queue(store)
    queue.enqueue("document_ingest", payload())
    job = queue.reserve()

    assert queue.fail(job, "LlamaParse timed out") == "retry"
    assert store.zcard(queue.retry_key) == 1
    assert store.llen(queue.pending_key) == 0  # backing off, not retried instantly
    assert store.llen(queue.inflight_key()) == 0

    assert queue.promote_due_retries() == 0  # not due yet
    store.zsets[queue.retry_key] = {k: 0.0 for k in store.zsets[queue.retry_key]}  # time passes
    assert queue.promote_due_retries() == 1
    assert queue.reserve().attempts == 1


def test_retries_stop_at_max_attempts_and_dead_letter():
    store = FakeRedis()
    queue = make_queue(store, max_attempts=3)
    queue.enqueue("document_ingest", payload())

    outcomes = []
    for _ in range(3):
        store.zsets[queue.retry_key] = {k: 0.0 for k in store.zsets.get(queue.retry_key, {})}
        queue.promote_due_retries()
        job = queue.reserve()
        outcomes.append(queue.fail(job, "still broken"))

    assert outcomes == ["retry", "retry", "dead"]
    assert store.llen(queue.dead_key) == 1

    dead = queue.dead_letters()
    assert dead[0]["attempts"] == 3
    assert dead[0]["last_error"] == "still broken"
    assert store.llen(queue.pending_key) == 0  # no longer retried


def test_dead_letters_are_scoped_and_replayable_per_workspace():
    store = FakeRedis()
    queue = make_queue(store, max_attempts=1)
    for tenant, doc in ((TENANT, "doc_mine"), (OTHER_TENANT, "doc_theirs")):
        queue.enqueue("document_ingest", payload(tenant, doc))
        queue.fail(queue.reserve(), "boom")

    assert {e["payload"]["doc_id"] for e in queue.dead_letters()} == {"doc_mine", "doc_theirs"}
    mine = queue.dead_letters_for(TENANT)
    assert [e["payload"]["doc_id"] for e in mine] == ["doc_mine"]

    assert queue.replay_dead_letters(tenant_id=TENANT) == 1
    assert queue.reserve().payload["doc_id"] == "doc_mine"
    # The other workspace's job stays dead-lettered, not requeued.
    assert [e["payload"]["doc_id"] for e in queue.dead_letters()] == ["doc_theirs"]


def test_replayed_job_gets_a_fresh_attempt_count():
    store = FakeRedis()
    queue = make_queue(store, max_attempts=1)
    queue.enqueue("document_ingest", payload())
    queue.fail(queue.reserve(), "boom")

    assert queue.dead_letters()[0]["attempts"] == 1
    queue.replay_dead_letters(tenant_id=TENANT)
    assert queue.reserve().attempts == 0


# --- visibility and fallback ---------------------------------------------
def test_stats_report_depth_and_backend():
    store = FakeRedis()
    queue = make_queue(store)
    queue.enqueue("document_ingest", payload())
    queue.enqueue("document_ingest", payload(doc_id="doc_2"))
    queue.reserve()

    stats = queue.stats()
    assert stats["backend"] == "redis"
    assert stats["pending"] == 1
    assert stats["inflight"] == 1
    assert "warning" not in stats


def test_memory_fallback_still_works_but_says_so():
    """Without Redis the queue must keep working - and must not claim durability."""
    queue = DurableQueue(name="test:ingest", client=None, consumer_id="w", max_attempts=2)
    queue._client = None  # no broker reachable

    queue.enqueue("document_ingest", payload())
    stats = queue.stats()
    assert stats["backend"] == "memory"
    assert stats["pending"] == 1
    assert "restart" in stats["warning"]

    job = queue.reserve()
    assert job.payload["doc_id"] == "doc_1"
    assert queue.fail(job, "boom") == "retry"
    assert queue.fail(queue.reserve(), "boom") == "dead"
    assert len(queue.dead_letters()) == 1


def test_job_survives_json_round_trip():
    job = Job(kind="document_ingest", payload=payload(), attempts=2, last_error="nope")
    restored = Job.from_json(job.to_json())

    assert restored.job_id == job.job_id
    assert restored.kind == job.kind
    assert restored.payload == job.payload
    assert restored.attempts == 2
    assert restored.last_error == "nope"


def test_enqueue_returns_only_after_the_job_is_recorded():
    store = FakeRedis()
    queue = make_queue(store)
    job = queue.enqueue("document_ingest", payload())

    # The API answers "queued" only once this is true.
    assert store.llen(queue.pending_key) == 1
    assert job.job_id in store.lists[queue.pending_key][0]
