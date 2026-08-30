from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Any
from connectors.connector_service import ConnectorService
from connectors.reconciliation_sweeper import ReconciliationSweeper

router = APIRouter(prefix="/connectors", tags=["connectors"])
connector_service = ConnectorService()
reconciliation_sweeper = ReconciliationSweeper()

class ConnectRequest(BaseModel):
    user_id: str

class ReconcileRequest(BaseModel):
    tenant_id: str
    live_docs: list[dict[str, Any]] = []

@router.post("/{source}/connect")
async def connect_source(source: str, request: ConnectRequest):
    try:
        res = connector_service.connect_source_with_auth(source=source, user_id=request.user_id)
        return {
            "status": "success",
            "source": source,
            "user_id": request.user_id,
            "trigger_id": res.get("trigger_id"),
            "redirect_url": res.get("redirect_url"),
        }
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Failed to set up trigger for {source}: {str(err)}")

@router.post("/{source}/reconcile")
async def reconcile_source(source: str, request: ReconcileRequest):
    try:
        report = reconciliation_sweeper.sweep_source(
            tenant_id=request.tenant_id,
            source=source,
            live_source_docs=request.live_docs,
        )
        return {
            "status": "success",
            "source": source,
            "tenant_id": request.tenant_id,
            "report": {
                "total_checked": report.total_checked,
                "missed_deletions_found": report.missed_deletions_found,
                "acl_drift_found": report.acl_drift_found,
                "corrections_applied": report.corrections_applied,
            },
        }
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Failed to execute reconciliation sweep for {source}: {str(err)}")
