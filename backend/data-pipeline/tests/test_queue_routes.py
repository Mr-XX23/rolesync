"""Ingestion queue visibility endpoints.

A stuck ingestion used to be undiagnosable: no queue depth, and a job that failed
every retry left no trace. These check that an operator can see the backlog and
the failures, that the answer says plainly whether work is actually durable, and
that one workspace can neither read nor replay another's jobs.
"""
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
OTHER_WORKSPACE = str(uuid.uuid4())
OWNER, VIEWER, OUTSIDER = (str(uuid.uuid4()) for _ in range(3))
ROLES = {
    OWNER: {WORKSPACE: "OWNER"},
    VIEWER: {WORKSPACE: "VIEWER"},
    OUTSIDER: {OTHER_WORKSPACE: "OWNER"},
}


@pytest.fixture
def queue(monkeypatch) -> DurableQueue:
    queue = DurableQueue(name="t:routes", client=FakeRedis(), consumer_id="w1", max_attempts=1)
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


def send(client, user, method, path, workspace=WORKSPACE):
    return client.request(method, "/api/v1" + path, headers={"X-User-Id": user, "X-Tenant-Id": workspace})


def fail_job(queue, tenant_id, doc_id):
    queue.enqueue("document_ingest", {"doc_id": doc_id, "tenant_id": tenant_id, "filename": f"{doc_id}.pdf"})
    queue.fail(queue.reserve(), "LlamaParse returned 500")


def test_stats_show_the_backlog_and_whether_it_is_durable(client, queue):
    queue.enqueue("document_ingest", {"doc_id": "doc_1", "tenant_id": WORKSPACE})

    body = send(client, OWNER, "GET", "/ingestion/queue/stats").json()

    assert body["durable"] is True
    assert body["queue"]["pending"] == 1
    assert body["queue"]["backend"] == "redis"


def test_stats_do_not_claim_durability_without_a_broker(client, queue):
    queue._client = None  # Redis unreachable

    body = send(client, OWNER, "GET", "/ingestion/queue/stats").json()

    assert body["durable"] is False
    assert body["queue"]["backend"] == "memory"
    assert "restart" in body["queue"]["warning"]


def test_dead_letters_show_why_a_document_failed(client, queue):
    fail_job(queue, WORKSPACE, "doc_mine")

    body = send(client, OWNER, "GET", "/ingestion/queue/dead-letters").json()

    assert body["count"] == 1
    entry = body["dead_letters"][0]
    assert entry["doc_id"] == "doc_mine"
    assert entry["filename"] == "doc_mine.pdf"
    assert entry["last_error"] == "LlamaParse returned 500"
    assert entry["attempts"] == 1


def test_another_workspaces_failures_are_invisible(client, queue):
    fail_job(queue, WORKSPACE, "doc_mine")
    fail_job(queue, OTHER_WORKSPACE, "doc_theirs")

    body = send(client, OWNER, "GET", "/ingestion/queue/dead-letters").json()

    assert [e["doc_id"] for e in body["dead_letters"]] == ["doc_mine"]


def test_replay_only_requeues_your_own_workspaces_jobs(client, queue):
    fail_job(queue, WORKSPACE, "doc_mine")
    fail_job(queue, OTHER_WORKSPACE, "doc_theirs")

    body = send(client, OWNER, "POST", "/ingestion/queue/dead-letters/replay").json()

    assert body["replayed"] == 1
    assert queue.reserve().payload["doc_id"] == "doc_mine"
    assert [e["payload"]["doc_id"] for e in queue.dead_letters()] == ["doc_theirs"]


def test_viewers_can_look_but_not_replay(client, queue):
    fail_job(queue, WORKSPACE, "doc_mine")

    assert send(client, VIEWER, "GET", "/ingestion/queue/dead-letters").status_code == 200

    refused = send(client, VIEWER, "POST", "/ingestion/queue/dead-letters/replay")
    assert refused.status_code == 403
    assert refused.json()["detail"] == "Viewers can't make changes in this workspace"


def test_non_members_are_refused(client):
    assert send(client, OUTSIDER, "GET", "/ingestion/queue/stats").status_code == 403
    assert send(client, OUTSIDER, "GET", "/ingestion/queue/dead-letters").status_code == 403
