"""The knowledge vault is shared per workspace: members see each other's documents, other
workspaces see nothing, and only the uploader or an owner/admin deletes.

Runs the real routes with MongoDB unreachable (in-memory store), workspace-service faked,
and document parsing skipped.
"""

import os
import uuid

os.environ.setdefault("MONGODB_URI", "mongodb://127.0.0.1:1")  # force the in-memory store

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from module_1_document_processing import knowledge_vault_routes, workspace_access
from module_1_document_processing.workspace_access import MembershipDirectory

WORKSPACE = str(uuid.uuid4())
OTHER_WORKSPACE = str(uuid.uuid4())
OWNER, MEMBER, VIEWER, OUTSIDER = (str(uuid.uuid4()) for _ in range(4))
ROLES = {
    OWNER: {WORKSPACE: "OWNER"},
    MEMBER: {WORKSPACE: "MEMBER"},
    VIEWER: {WORKSPACE: "VIEWER"},
    OUTSIDER: {OTHER_WORKSPACE: "OWNER"},
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        workspace_access, "directory", MembershipDirectory("http://workspace.test", fetch=lambda base, user, t: ROLES.get(user, {}))
    )
    monkeypatch.setattr(knowledge_vault_routes, "_process_document_background", lambda **kwargs: None)
    knowledge_vault_routes._in_memory_docs.clear()
    app = FastAPI()
    app.include_router(knowledge_vault_routes.router, prefix="/api/v1")
    return TestClient(app)


def _as(user, workspace=WORKSPACE):
    return {"X-User-Id": user, "X-Tenant-Id": workspace}


def _upload(client, user, name="battlecard.md"):
    return client.post(
        "/api/v1/knowledge-vault/upload",
        headers=_as(user),
        files={"file": (name, b"# Globex battlecard\nWe win on price.", "text/markdown")},
        data={"user_id": "someone-else"},  # a client-chosen user id is ignored
    )


def test_uploads_belong_to_the_workspace_and_record_the_verified_uploader(client):
    uploaded = _upload(client, MEMBER)
    assert uploaded.status_code == 200, uploaded.text
    doc = uploaded.json()["document"]
    assert (doc["tenant_id"], doc["user_id"]) == (WORKSPACE, MEMBER)

    # Every member sees it; ?mine=true narrows to the caller's own uploads.
    listed = client.get("/api/v1/knowledge-vault/documents", headers=_as(OWNER)).json()
    assert [d["doc_id"] for d in listed["documents"]] == [doc["doc_id"]]
    assert client.get("/api/v1/knowledge-vault/documents?mine=true", headers=_as(OWNER)).json()["count"] == 0
    assert client.get("/api/v1/knowledge-vault/stats", headers=_as(VIEWER)).json()["stats"]["total_documents"] == 1


def test_other_workspaces_cannot_see_or_reach_the_document(client):
    doc_id = _upload(client, MEMBER).json()["document"]["doc_id"]

    assert client.get("/api/v1/knowledge-vault/documents", headers=_as(OUTSIDER, OTHER_WORKSPACE)).json()["count"] == 0
    # Claiming the workspace without being a member of it:
    assert client.get(f"/api/v1/knowledge-vault/documents/{doc_id}/content", headers=_as(OUTSIDER)).status_code == 403
    # Through their own workspace the document doesn't exist:
    assert client.get(f"/api/v1/knowledge-vault/documents/{doc_id}/content", headers=_as(OUTSIDER, OTHER_WORKSPACE)).status_code == 404
    assert client.delete(f"/api/v1/knowledge-vault/documents/{doc_id}", headers=_as(OUTSIDER, OTHER_WORKSPACE)).status_code == 404


def test_a_workspace_is_required(client):
    assert client.get("/api/v1/knowledge-vault/documents", headers={"X-User-Id": MEMBER}).status_code == 400
    assert client.get("/api/v1/knowledge-vault/documents", headers=_as(MEMBER, "tenant_default")).status_code == 400
    assert client.get("/api/v1/knowledge-vault/documents", headers={"X-Tenant-Id": WORKSPACE}).status_code == 401


def test_only_the_uploader_or_an_admin_deletes_and_viewers_only_read(client):
    doc_id = _upload(client, MEMBER).json()["document"]["doc_id"]
    assert _upload(client, VIEWER).status_code == 403

    assert client.delete(f"/api/v1/knowledge-vault/documents/{doc_id}", headers=_as(VIEWER)).status_code == 403
    other = _upload(client, OWNER).json()["document"]["doc_id"]
    assert client.delete(f"/api/v1/knowledge-vault/documents/{other}", headers=_as(MEMBER)).status_code == 403

    assert client.delete(f"/api/v1/knowledge-vault/documents/{doc_id}", headers=_as(MEMBER)).status_code == 200
    assert client.delete(f"/api/v1/knowledge-vault/documents/{other}", headers=_as(OWNER)).status_code == 200
