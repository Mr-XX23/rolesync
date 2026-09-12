"""Gatekeeper visibility and review endpoints.

The gatekeeper decides what never enters the knowledge base, so those decisions
need to be inspectable and reversible: previously they were written to an
in-process list with no way to read them, and quarantined documents could not be
reviewed or replayed.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from module_1_document_processing.identity import bind_identity
from module_1_document_processing.workspace_access import (
    WorkspaceAccess,
    require_workspace_member,
    require_writer,
)
from module_2_memory_gatekeeper.gatekeeper_store import gatekeeper_store
from module_2_memory_gatekeeper.policy import load_policy
from module_2_memory_gatekeeper.semantic_scorer import semantic_scorer

router = APIRouter(tags=["Gatekeeper"], dependencies=[Depends(bind_identity)])


class ReleaseResponse(BaseModel):
    status: str
    doc_id: str
    message: str


@router.get("/gatekeeper/policy")
def get_gatekeeper_policy(access: WorkspaceAccess = Depends(require_workspace_member)):
    """The active policy, including whether the semantic scorer is enforced."""
    policy = load_policy()
    return {
        "status": "success",
        "policy": policy.describe(),
        "semantic_scorer_available": semantic_scorer.available(),
        "mode": "enforcing" if policy.semantic_enforced else "log-only",
    }


@router.get("/gatekeeper/decisions/{doc_id}")
def get_decisions(doc_id: str, access: WorkspaceAccess = Depends(require_workspace_member)):
    """Audit trail for one document: what was decided, why, and under which policy."""
    decisions = gatekeeper_store.decisions_for_doc(doc_id, tenant_id=access.workspace_id)
    return {"status": "success", "doc_id": doc_id, "count": len(decisions), "decisions": decisions}


@router.get("/gatekeeper/holds")
def list_holds(
    kind: Optional[str] = Query(default=None, description="REJECTED or QUARANTINED"),
    limit: int = Query(default=100, ge=1, le=500),
    access: WorkspaceAccess = Depends(require_workspace_member),
):
    """Documents the gatekeeper kept out, with the reason and a content preview."""
    if kind and kind.upper() not in ("REJECTED", "QUARANTINED"):
        raise HTTPException(status_code=400, detail="kind must be REJECTED or QUARANTINED.")

    holds = gatekeeper_store.list_holds(access.workspace_id, kind=(kind or ""), limit=limit)
    return {
        "status": "success",
        "count": len(holds),
        "holds": [
            {
                "doc_id": h.doc_id,
                "kind": h.kind,
                "source": h.source,
                "category": h.category,
                "reason": h.reason,
                "preview": h.preview,
                "char_count": h.char_count,
                "semantic_score": h.semantic_score,
                "status": h.status,
                "created_at": h.created_at.isoformat() if h.created_at else None,
                "expires_at": h.expires_at.isoformat() if h.expires_at else None,
            }
            for h in holds
        ],
    }


@router.post("/gatekeeper/holds/{doc_id}/release", response_model=ReleaseResponse)
def release_hold(doc_id: str, access: WorkspaceAccess = Depends(require_workspace_member)):
    """Release a held document after human review, so it can be re-ingested."""
    require_writer(access)

    hold = gatekeeper_store.get_hold(doc_id, tenant_id=access.workspace_id)
    # Anything not still HELD (already released) is not releasable, and must read
    # the same as absent rather than reporting a second success.
    if not hold or hold.status != "HELD":
        raise HTTPException(status_code=404, detail="No held document with that id.")

    # Release by the canonical id the hold is stored under, not the caller's form.
    if not gatekeeper_store.release(hold.doc_id):
        raise HTTPException(status_code=409, detail="That document could not be released.")

    return ReleaseResponse(
        status="success",
        doc_id=doc_id,
        message="Released for replay. Re-upload or re-index the document to ingest it.",
    )


@router.post("/gatekeeper/holds/purge-expired")
def purge_expired(access: WorkspaceAccess = Depends(require_workspace_member)):
    """Delete holds past their TTL."""
    require_writer(access)
    removed = gatekeeper_store.purge_expired()
    return {"status": "success", "removed": removed, "message": f"Purged {removed} expired hold(s)."}
