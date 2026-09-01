from fastapi import APIRouter, HTTPException, Query, Header
from pydantic import BaseModel, Field
from typing import Any
from module_1_document_processing.composio_connector.connector_service import ConnectorService
from module_1_document_processing.composio_connector.gmail_sync_manager import GmailSyncManager

router = APIRouter(tags=["Connectors"])
connector_service = ConnectorService()
gmail_sync_manager = GmailSyncManager()

class ConnectRequest(BaseModel):
    user_id: str = "usr_active"

class GmailConfigRequest(BaseModel):
    user_id: str = "usr_active"
    max_emails_per_sync: int = Field(default=10, ge=1, le=30)
    categories: list[str] = Field(default_factory=lambda: ["INBOX"])
    sync_window_days: int = 90

class GmailActionRequest(BaseModel):
    user_id: str = "usr_active"

@router.post("/connectors/{source}/connect")
def connect_connector(source: str, req: ConnectRequest, x_tenant_id: str = Header(default="tenant_default")):
    if source.lower() == "gmail":
        res = gmail_sync_manager.initiate_oauth_flow(user_id=req.user_id, tenant_id=x_tenant_id)
        return res

    res = connector_service.connect_source(user_id=req.user_id, source=source)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

@router.post("/connectors/gmail/config")
async def save_gmail_config(req: GmailConfigRequest, x_tenant_id: str = Header(default="tenant_default")):
    res = await gmail_sync_manager.save_configuration_and_start_sync(
        user_id=req.user_id,
        tenant_id=x_tenant_id,
        config_data=req.model_dump(),
    )
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

@router.get("/connectors/gmail/status")
def get_gmail_status(user_id: str = "usr_active", x_tenant_id: str = Header(default="tenant_default")):
    conn = gmail_sync_manager.store.get_or_create_connection(tenant_id=x_tenant_id, user_id=user_id)
    return {
        "status": "success",
        "connection": conn.to_dict(),
    }

@router.post("/connectors/gmail/sync-now")
async def trigger_gmail_sync_now(req: GmailActionRequest, x_tenant_id: str = Header(default="tenant_default")):
    res = await gmail_sync_manager.trigger_manual_sync(user_id=req.user_id, tenant_id=x_tenant_id)
    if res.get("status") == "locked":
        raise HTTPException(status_code=409, detail=res.get("message"))
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

@router.post("/connectors/gmail/resync")
async def trigger_gmail_resync(req: GmailActionRequest, x_tenant_id: str = Header(default="tenant_default")):
    res = await gmail_sync_manager.trigger_resync(user_id=req.user_id, tenant_id=x_tenant_id)
    if res.get("status") == "locked":
        raise HTTPException(status_code=409, detail=res.get("message"))
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

@router.get("/connectors/gmail/activities")
def get_gmail_activities(
    user_id: str = "usr_active",
    limit: int = 20,
    x_tenant_id: str = Header(default="tenant_default"),
):
    conn = gmail_sync_manager.store.get_or_create_connection(tenant_id=x_tenant_id, user_id=user_id)
    activities = gmail_sync_manager.store.get_activities(connection_id=conn.connection_id, limit=limit)
    return {
        "status": "success",
        "connection_id": conn.connection_id,
        "activities": [act.to_dict() for act in activities],
    }

@router.post("/connectors/gmail/disconnect")
def disconnect_gmail(req: GmailActionRequest, x_tenant_id: str = Header(default="tenant_default")):
    res = gmail_sync_manager.disconnect_connection(user_id=req.user_id, tenant_id=x_tenant_id)
    return res
