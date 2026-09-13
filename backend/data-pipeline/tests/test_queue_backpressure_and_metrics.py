"""Backpressure and visibility for the ingestion queue.

A durable queue will happily accept an unbounded backlog, still answering "queued
for parsing" for work it will not reach for hours. And a backlog that has stopped
draining looks identical to a healthy one if depth is the only thing measured -
which is why queue *age* is reported alongside it.
"""
import time
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from module_1_document_processing import workspace_access
from module_1_document_processing.pipeline import queue_routes
from module_1_document_processing.pipeline.durable_queue import DurableQueue
from module_1_document_processing.workspace_access import MembershipDirectory
from tests.fake_redis import FakeRedis

WORKSPACE = str(uuid.uuid4())
OWNER = str(uuid.uuid4())
ROLES = {OWNER: {WORKSPACE: "OWNER"}}


def make_queue(max_depth: int = 0, **kwargs) -> DurableQueue:
    return DurableQueue(
        name="t:bp", client=FakeRedis(), consumer_id="w1",
        max_attempts=kwargs.pop("max_attempts", 2), max_depth=max_depth, **kwargs,
    )


def payload(doc_id: str = "doc_1") -> dict:
    return {"doc_id": doc_id, "tenant_id": WORKSPACE, "filename": f"{doc_id}.pdf"}


# --- depth and backpressure ----------------------------------------------
def test_depth_counts_waiting_and_retrying_work():
    """A job waiting on a backoff is still backlog, so it counts."""
    queue = make_queue()
    queue.enqueue("doc", payload("doc_1"))
    queue.enqueue("doc", payload("doc_2"))
    queue.fail(queue.reserve(), "boom")  # moves one into the retry set

    assert queue.depth() == 2


def test_no_limit_means_always_accepting():
    queue = make_queue(max_depth=0)
    for i in range(50):
        queue.enqueue("doc", payload(f"doc_{i}"))

    assert queue.is_overloaded() is False
    assert queue.stats()["accepting"] is True


def test_the_queue_reports_overloaded_at_its_limit():
    queue = make_queue(max_depth=3)
    for i in range(2):
        queue.enqueue("doc", payload(f"doc_{i}"))
    assert queue.is_overloaded() is False

    queue.enqueue("doc", payload("doc_3"))

    assert queue.is_overloaded() is True
    assert queue.stats()["accepting"] is False


def test_draining_the_backlog_reopens_the_gate():
    queue = make_queue(max_depth=1)
    queue.enqueue("doc", payload())
    assert queue.is_overloaded() is True

    queue.ack(queue.reserve())

    assert queue.is_overloaded() is False


def test_the_limit_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("INGEST_QUEUE_MAX_DEPTH", "7")
    assert DurableQueue(name="t:bp", client=FakeRedis(), consumer_id="w1").max_depth == 7


# --- queue age ------------------------------------------------------------
def test_age_reports_the_longest_wait_not_the_newest():
    """Depth alone can look healthy while nothing drains; age is what shows it."""
    queue = make_queue()
    store = queue._client
    old = {"job_id": "job_old", "kind": "doc", "payload": payload("doc_old"),
           "attempts": 0, "enqueued_at": time.time() - 600, "last_error": ""}
    import json

    store.rpush(queue.pending_key, json.dumps(old))  # tail = oldest
    queue.enqueue("doc", payload("doc_new"))

    assert queue.oldest_pending_age_seconds() >= 600
    assert queue.stats()["oldest_pending_age_seconds"] >= 600


def test_an_empty_queue_has_no_age():
    assert make_queue().oldest_pending_age_seconds() == 0.0


def test_unreadable_queue_content_does_not_break_the_age_reading():
    queue = make_queue()
    queue._client.rpush(queue.pending_key, "not json")

    assert queue.oldest_pending_age_seconds() == 0.0


# --- counters -------------------------------------------------------------
def test_outcomes_are_counted():
    queue = make_queue(max_attempts=2)
    queue.enqueue("doc", payload("doc_1"))
    queue.enqueue("doc", payload("doc_2"))
    queue.ack(queue.reserve())
    queue.fail(queue.reserve(), "boom")          # retry
    queue.promote_due_retries()

    totals = queue.counters()
    assert totals["enqueued"] == 2
    assert totals["processed"] == 1
    assert totals["retried"] == 1
    assert totals["dead"] == 0


def test_giving_up_is_counted_separately_from_retrying():
    queue = make_queue(max_attempts=1)
    queue.enqueue("doc", payload())
    queue.fail(queue.reserve(), "boom")

    totals = queue.counters()
    assert totals["dead"] == 1
    assert totals["retried"] == 0


def test_counters_work_without_redis():
    queue = DurableQueue(name="t:bp", client=None, consumer_id="w1", max_attempts=1)
    queue._client = None
    queue.enqueue("doc", payload())
    queue.ack(queue.reserve())

    assert queue.counters()["processed"] == 1


# --- the metrics endpoint -------------------------------------------------
@pytest.fixture
def queue(monkeypatch) -> DurableQueue:
    queue = make_queue(max_depth=5)
    monkeypatch.setattr(queue_routes, "ingest_queue", queue)
    return queue


@pytest.fixture
def client(monkeypatch, queue) -> TestClient:
    monkeypatch.setattr(
        workspace_access,
        "directory",
        MembershipDirectory("http://workspace.test", fetch=lambda base, user, t: ROLES.get(user, {})),
    )
    app = FastAPI()
    app.include_router(queue_routes.router, prefix="/api/v1")
    return TestClient(app)


def get(client, path, user=OWNER):
    return client.get("/api/v1" + path, headers={"X-User-Id": user, "X-Tenant-Id": WORKSPACE})


def test_metrics_are_prometheus_text(client, queue):
    queue.enqueue("doc", payload())

    response = get(client, "/ingestion/queue/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert 'rolesync_ingest_queue_depth{state="pending"} 1' in body
    assert "# TYPE rolesync_ingest_queue_depth gauge" in body
    assert 'rolesync_ingest_jobs_total{outcome="enqueued"} 1' in body


def test_metrics_expose_durability_and_acceptance(client, queue):
    body = get(client, "/ingestion/queue/metrics").text
    assert "rolesync_ingest_queue_durable 1" in body
    assert "rolesync_ingest_queue_accepting 1" in body

    for i in range(5):
        queue.enqueue("doc", payload(f"doc_{i}"))

    assert "rolesync_ingest_queue_accepting 0" in get(client, "/ingestion/queue/metrics").text


def test_metrics_report_no_durability_without_redis(client, queue):
    queue._client = None

    assert "rolesync_ingest_queue_durable 0" in get(client, "/ingestion/queue/metrics").text


def test_stats_expose_age_limit_and_totals(client, queue):
    queue.enqueue("doc", payload())

    body = get(client, "/ingestion/queue/stats").json()["queue"]

    assert body["max_depth"] == 5
    assert body["accepting"] is True
    assert "oldest_pending_age_seconds" in body
    assert body["totals"]["enqueued"] == 1


def test_metrics_need_workspace_membership(client):
    outsider = str(uuid.uuid4())
    assert get(client, "/ingestion/queue/metrics", user=outsider).status_code == 403
