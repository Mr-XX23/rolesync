"""Gatekeeper review endpoints: who may read decisions, and who may release holds.

Runs the real routes with workspace-service faked, against an in-memory store.
What matters here is that a workspace only ever sees its own decisions and holds,
that viewers can read but not release, and that a release is not repeatable.
"""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from module_1_document_processing import workspace_access
from module_1_document_processing.workspace_access import MembershipDirectory
from module_2_memory_gatekeeper import gatekeeper_routes
from module_2_memory_gatekeeper.gatekeeper_engine import DECISION_ACCEPTED, DECISION_REJECTED_LEXICAL
from module_2_memory_gatekeeper.gatekeeper_store import KIND_QUARANTINED, KIND_REJECTED, GatekeeperStore

from tests.test_gatekeeper_policy_and_store import make_doc

WORKSPACE = str(uuid.uuid4())
OTHER_WORKSPACE = str(uuid.uuid4())
OWNER, VIEWER, OUTSIDER = (str(uuid.uuid4()) for _ in range(3))
ROLES = {
    OWNER: {WORKSPACE: "OWNER"},
    VIEWER: {WORKSPACE: "VIEWER"},
    OUTSIDER: {OTHER_WORKSPACE: "OWNER"},
}

HELD_DOC = f"{WORKSPACE}:USER_UPLOAD:doc_held01"
FOREIGN_DOC = f"{OTHER_WORKSPACE}:USER_UPLOAD:doc_other1"


@pytest.fixture
def store(monkeypatch):
    store = GatekeeperStore(use_db=False)
    monkeypatch.setattr(gatekeeper_routes, "gatekeeper_store", store)

    store.hold(KIND_REJECTED, make_doc(doc_id=HELD_DOC, tenant_id=WORKSPACE), "repetitive noise", ttl_days=30)
    store.record_decision(
        doc_id=HELD_DOC, tenant_id=WORKSPACE, user_id=OWNER, source="USER_UPLOAD",
        category="general_doc", decision=DECISION_REJECTED_LEXICAL, reason="repetitive noise",
    )
    # Another workspace's document, which must never be visible here.
    store.hold(KIND_QUARANTINED, make_doc(doc_id=FOREIGN_DOC, tenant_id=OTHER_WORKSPACE), "low utility", ttl_days=90)
    store.record_decision(
        doc_id=FOREIGN_DOC, tenant_id=OTHER_WORKSPACE, user_id=OUTSIDER, source="USER_UPLOAD",
        category="general_doc", decision=DECISION_ACCEPTED, reason="ok",
    )
    return store


@pytest.fixture
def client(monkeypatch, store):
    monkeypatch.setattr(
        workspace_access,
        "directory",
        MembershipDirectory("http://workspace.test", fetch=lambda base, user, t: ROLES.get(user, {})),
    )
    app = FastAPI()
    app.include_router(gatekeeper_routes.router, prefix="/api/v1")
    return TestClient(app)


def send(client, user, method, path, workspace=WORKSPACE):
    return client.request(method, "/api/v1" + path, headers={"X-User-Id": user, "X-Tenant-Id": workspace})


def test_policy_is_visible_and_reports_its_mode(client):
    body = send(client, VIEWER, "GET", "/gatekeeper/policy").json()
    assert body["mode"] in ("log-only", "enforcing")
    assert body["mode"] == ("enforcing" if body["policy"]["semantic_enforced"] else "log-only")
    assert body["policy"]["version"].startswith("gk-")


def test_holds_and_decisions_are_scoped_to_the_workspace(client):
    holds = send(client, OWNER, "GET", "/gatekeeper/holds").json()
    assert [h["doc_id"] for h in holds["holds"]] == [HELD_DOC]

    # The other workspace's document is invisible even when asked for by id.
    assert send(client, OWNER, "GET", f"/gatekeeper/decisions/{FOREIGN_DOC}").json()["count"] == 0
    assert send(client, OWNER, "POST", f"/gatekeeper/holds/{FOREIGN_DOC}/release").status_code == 404


def test_a_non_member_is_refused(client):
    assert send(client, OUTSIDER, "GET", "/gatekeeper/holds").status_code == 403
    assert send(client, OUTSIDER, "GET", "/gatekeeper/policy").status_code == 403


def test_decisions_resolve_either_id_form(client):
    by_canonical = send(client, OWNER, "GET", f"/gatekeeper/decisions/{HELD_DOC}").json()
    by_short = send(client, OWNER, "GET", "/gatekeeper/decisions/doc_held01").json()

    assert by_canonical["count"] == by_short["count"] == 1
    assert by_short["decisions"][0]["decision"] == DECISION_REJECTED_LEXICAL
    assert by_short["decisions"][0]["reason"] == "repetitive noise"


def test_viewers_can_read_but_not_release_or_purge(client):
    assert send(client, VIEWER, "GET", "/gatekeeper/holds").status_code == 200

    for method, path in (("POST", "/gatekeeper/holds/doc_held01/release"),
                         ("POST", "/gatekeeper/holds/purge-expired")):
        refused = send(client, VIEWER, method, path)
        assert refused.status_code == 403
        assert refused.json()["detail"] == "Viewers can't make changes in this workspace"


def test_release_clears_the_hold_and_is_not_repeatable(client, store):
    assert send(client, OWNER, "POST", "/gatekeeper/holds/doc_held01/release").status_code == 200
    assert send(client, OWNER, "GET", "/gatekeeper/holds").json()["count"] == 0
    assert store.get_hold(HELD_DOC, tenant_id=WORKSPACE).status == "RELEASED"

    # A second release must not report success again.
    assert send(client, OWNER, "POST", "/gatekeeper/holds/doc_held01/release").status_code == 404


def test_unknown_hold_and_bad_filter_are_rejected(client):
    assert send(client, OWNER, "POST", "/gatekeeper/holds/nope/release").status_code == 404

    bad = send(client, OWNER, "GET", "/gatekeeper/holds?kind=bogus")
    assert bad.status_code == 400
    assert bad.json()["detail"] == "kind must be REJECTED or QUARANTINED."

    assert send(client, OWNER, "GET", "/gatekeeper/holds?kind=quarantined").json()["count"] == 0


def test_tenant_header_is_required_and_validated(client):
    assert client.get("/api/v1/gatekeeper/holds", headers={"X-User-Id": OWNER}).status_code == 400
    assert send(client, OWNER, "GET", "/gatekeeper/holds", workspace="not-a-uuid").status_code == 400
