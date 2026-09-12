"""On-demand reconciliation endpoints.

Scheduled sweeps are off by default because each one spends Composio tool
executions, so this gives an explicit way to run and inspect one.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from module_1_document_processing.del_acl_and_reconc.reconciliation_scheduler import (
    reconciliation_scheduler,
)
from module_1_document_processing.identity import bind_identity
from module_1_document_processing.workspace_access import (
    WorkspaceAccess,
    require_workspace_member,
    require_writer,
)

router = APIRouter(tags=["Reconciliation"], dependencies=[Depends(bind_identity)])


class SweepRequest(BaseModel):
    source: Optional[str] = None  # gdrive | notion | calendar; omit for all
    mine_only: bool = True        # restrict to the calling user's connections


@router.get("/reconciliation/status")
def reconciliation_status(access: WorkspaceAccess = Depends(require_workspace_member)):
    """Whether scheduled sweeps are on, how often, and when one last ran."""
    return {
        "status": "success",
        "enabled": reconciliation_scheduler.enabled,
        "interval_minutes": reconciliation_scheduler.interval_minutes,
        "last_sweep_at": (
            reconciliation_scheduler.last_sweep_at.isoformat()
            if reconciliation_scheduler.last_sweep_at
            else None
        ),
        "sweepable_sources": sorted(reconciliation_scheduler.providers.keys()),
    }


@router.post("/reconciliation/sweep")
async def run_reconciliation_sweep(
    req: SweepRequest,
    access: WorkspaceAccess = Depends(require_workspace_member),
):
    """Re-list connected sources and reconcile deletions / ACL drift now."""
    require_writer(access)

    reports = await asyncio.to_thread(
        reconciliation_scheduler.sweep_all,
        tenant_id=access.workspace_id,
        source_filter=(req.source or "").lower(),
        user_id=access.user_id if req.mine_only else "",
    )

    return {
        "status": "success",
        "swept_connections": len(reports),
        "reports": [
            {
                "source": r.source,
                "checked": r.total_checked,
                "missed_deletions": r.missed_deletions_found,
                "acl_drift": r.acl_drift_found,
                "corrections_applied": r.corrections_applied,
                "skipped_deletions": r.skipped_deletions,
                "aborted": r.aborted,
                "reason": r.reason,
            }
            for r in reports
        ],
        "message": (
            f"Reconciled {len(reports)} connection(s)."
            if reports
            else "No sweepable connections found. Mailboxes and chat histories are not swept."
        ),
    }
