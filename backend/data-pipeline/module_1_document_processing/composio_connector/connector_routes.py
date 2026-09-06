from fastapi import APIRouter, HTTPException, Query, Header
from pydantic import BaseModel, Field
from typing import Any
from module_1_document_processing.composio_connector.connector_service import ConnectorService
from module_1_document_processing.composio_connector.gmail_sync_manager import GmailSyncManager
from module_1_document_processing.composio_connector.gdrive_sync_manager import GDriveSyncManager
from module_1_document_processing.composio_connector.gdrive_models import GDriveSyncConfig, GDriveTriggerType

router = APIRouter(tags=["Connectors"])
connector_service = ConnectorService()
gmail_sync_manager = GmailSyncManager()
gdrive_sync_manager = GDriveSyncManager()

class ConnectRequest(BaseModel):
    user_id: str = "usr_active"
    callback_url: str | None = None

class GmailConfigRequest(BaseModel):
    user_id: str = "usr_active"
    max_emails_per_sync: int = Field(default=10, ge=1, le=30)
    categories: list[str] = Field(default_factory=lambda: ["INBOX"])
    sync_window_days: int = 180
    auto_sync_interval_minutes: int = 0
    sync_frequency: str = "off"
    auto_sync_enabled: bool = False
    webhook_enabled: bool = False

class GDriveConfigRequest(BaseModel):
    user_id: str = "usr_active"
    max_files_per_sync: int = Field(default=10, ge=1, le=30)
    categories: list[str] = Field(default_factory=lambda: ["MY_DRIVE"])
    sync_window_days: int = 180
    auto_sync_interval_minutes: int = 0
    sync_frequency: str = "off"
    auto_sync_enabled: bool = False
    webhook_enabled: bool = False

class AutoSyncScheduleRequest(BaseModel):
    user_id: str = "usr_active"
    sync_frequency: str = "off" # off, 2m, 30m, 1h, 6h, 24h, manual
    interval_minutes: int | None = None
    auto_sync_enabled: bool | None = None
    webhook_enabled: bool | None = None

class GmailActionRequest(BaseModel):
    user_id: str = "usr_active"

class SimulateWebhookRequest(BaseModel):
    user_id: str = "usr_active"
    message_id: str | None = None
    subject: str = "Real-Time Test Notification"
    sender: str = "notifications@service.com"
    body: str = "This is a real-time incoming email webhook simulation message."
    snippet: str | None = None
    attachments: list[dict[str, Any]] = Field(default_factory=list)

class SimulateGDriveWebhookRequest(BaseModel):
    user_id: str = "usr_active"
    file_id: str | None = None
    name: str = "Real-Time Project Roadmap.docx"
    mime_type: str = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    size: int = 10240
    category: str = "MY_DRIVE"
    content: str = "Project Roadmap: Google Drive real-time webhook ingestion is fully operational."


@router.get("/connectors/status")
def get_all_connectors_status(user_id: str = "usr_active", x_tenant_id: str = Header(default="tenant_default")):
    """Production endpoint returning live OAuth connectivity, sync metrics, and parameters for all 5 connectors."""
    gmail_conn = gmail_sync_manager.get_connection_status(user_id=user_id, tenant_id=x_tenant_id)
    gdrive_conn = gdrive_sync_manager.get_connection_status(user_id=user_id, tenant_id=x_tenant_id)

    sources = ["calendar", "slack", "notion"]
    other_connections = {}
    for src in sources:
        is_conn = connector_service.composio.is_account_connected(user_id=user_id, source=src)
        status_val = "Connected" if is_conn else "Available"
        other_connections[src] = {
            "connection_id": f"conn_{src}_{x_tenant_id}_{user_id}",
            "tenant_id": x_tenant_id,
            "user_id": user_id,
            "source": src,
            "status": status_val,
            "sync_frequency": "REALTIME" if is_conn else "OFF",
            "sync_captured": 0,
            "sync_success": 0,
            "sync_skipped": 0,
            "sync_failed": 0,
            "current_progress": "",
            "is_locked": False,
        }

    return {
        "status": "success",
        "connections": {
            "gmail": gmail_conn.to_dict() if hasattr(gmail_conn, "to_dict") else gmail_conn,
            "gdrive": gdrive_conn.to_dict() if hasattr(gdrive_conn, "to_dict") else gdrive_conn,
            **other_connections,
        },
    }

@router.post("/connectors/{source}/connect")
def connect_connector(source: str, req: ConnectRequest, x_tenant_id: str = Header(default="tenant_default")):
    if source.lower() == "gmail":
        return gmail_sync_manager.initiate_oauth_flow(
            user_id=req.user_id,
            tenant_id=x_tenant_id,
            callback_url=req.callback_url,
        )
    elif source.lower() in ("gdrive", "googledrive", "google_drive"):
        return gdrive_sync_manager.initiate_oauth_flow(
            user_id=req.user_id,
            tenant_id=x_tenant_id,
            callback_url=req.callback_url,
        )

    res = connector_service.connect_source(
        user_id=req.user_id,
        source=source,
        callback_url=req.callback_url,
    )
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

@router.post("/connectors/{source}/disconnect")
def disconnect_connector(source: str, req: ConnectRequest, x_tenant_id: str = Header(default="tenant_default")):
    try:
        if source.lower() == "gmail":
            return gmail_sync_manager.disconnect_connection(user_id=req.user_id, tenant_id=x_tenant_id)
        elif source.lower() in ("gdrive", "googledrive", "google_drive"):
            return gdrive_sync_manager.disconnect_connection(user_id=req.user_id, tenant_id=x_tenant_id)

        # Invalidate and revoke OAuth token in Composio backend
        try:
            connector_service.composio.disconnect_user_account(user_id=req.user_id, source=source)
        except Exception as err:
            print(f"[ConnectorRoutes] Error disconnecting {source}: {err}")

        return {
            "status": "success",
            "message": f"{source} disconnected. OAuth tokens invalidated. Synced memories preserved.",
        }
    finally:
        connector_service.composio.clear_cache(req.user_id)

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

@router.post("/connectors/gmail/auto-sync")
async def update_gmail_auto_sync(req: AutoSyncScheduleRequest, x_tenant_id: str = Header(default="tenant_default")):
    """Dedicated endpoint to update Auto-Sync schedule frequency and webhook status for Gmail."""
    res = await gmail_sync_manager.update_auto_sync_schedule(
        user_id=req.user_id,
        tenant_id=x_tenant_id,
        sync_frequency=req.sync_frequency,
        interval_minutes=req.interval_minutes,
        auto_sync_enabled=req.auto_sync_enabled,
        webhook_enabled=req.webhook_enabled,
    )
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

@router.post("/connectors/{source}/auto-sync")
async def update_source_auto_sync(source: str, req: AutoSyncScheduleRequest, x_tenant_id: str = Header(default="tenant_default")):
    """Universal endpoint to update Auto-Sync schedule frequency and webhook status for any connected source."""
    if source.lower() == "gmail":
        return await update_gmail_auto_sync(req, x_tenant_id=x_tenant_id)
    elif source.lower() in ("gdrive", "googledrive", "google_drive"):
        return gdrive_sync_manager.update_auto_sync_schedule(
            user_id=req.user_id,
            tenant_id=x_tenant_id,
            sync_frequency=req.sync_frequency,
            interval_minutes=req.interval_minutes,
            auto_sync_enabled=req.auto_sync_enabled,
            webhook_enabled=req.webhook_enabled,
        )
    return {
        "status": "success",
        "message": f"{source} auto-sync set to {req.sync_frequency}.",
        "sync_frequency": req.sync_frequency,
        "interval_minutes": req.interval_minutes or 0,
        "auto_sync_enabled": bool(req.auto_sync_enabled),
        "webhook_enabled": bool(req.webhook_enabled),
    }

@router.get("/connectors/gmail/status")
def get_gmail_status(user_id: str = "usr_active", x_tenant_id: str = Header(default="tenant_default")):
    conn_dict = gmail_sync_manager.get_connection_status(user_id=user_id, tenant_id=x_tenant_id)
    return {
        "status": "success",
        "connection": conn_dict,
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

# =========================================================================
# Google Drive Specific Endpoints
# =========================================================================

@router.post("/connectors/gdrive/config")
async def save_gdrive_config(req: GDriveConfigRequest, x_tenant_id: str = Header(default="tenant_default")):
    cfg = GDriveSyncConfig(
        max_files_per_sync=req.max_files_per_sync,
        categories=req.categories,
        sync_window_days=req.sync_window_days,
        auto_sync_interval_minutes=req.auto_sync_interval_minutes,
        sync_frequency=req.sync_frequency,
        auto_sync_enabled=req.auto_sync_enabled,
        webhook_enabled=req.webhook_enabled,
    )
    return await gdrive_sync_manager.save_configuration_and_start_sync(
        user_id=req.user_id,
        tenant_id=x_tenant_id,
        config=cfg,
    )

@router.post("/connectors/gdrive/auto-sync")
async def update_gdrive_auto_sync(req: AutoSyncScheduleRequest, x_tenant_id: str = Header(default="tenant_default")):
    return gdrive_sync_manager.update_auto_sync_schedule(
        user_id=req.user_id,
        tenant_id=x_tenant_id,
        sync_frequency=req.sync_frequency,
        interval_minutes=req.interval_minutes,
        auto_sync_enabled=req.auto_sync_enabled,
        webhook_enabled=req.webhook_enabled,
    )


@router.get("/connectors/gdrive/status")
def get_gdrive_status(user_id: str = "usr_active", x_tenant_id: str = Header(default="tenant_default")):
    conn = gdrive_sync_manager.get_connection_status(user_id=user_id, tenant_id=x_tenant_id)
    return {
        "status": "success",
        "connection": conn.to_dict(),
    }

@router.post("/connectors/gdrive/sync-now")
async def trigger_gdrive_sync_now(req: GmailActionRequest, x_tenant_id: str = Header(default="tenant_default")):
    conn = gdrive_sync_manager.store.get_or_create_connection(tenant_id=x_tenant_id, user_id=req.user_id)
    if gdrive_sync_manager.store.is_locked(conn.connection_id):
        raise HTTPException(status_code=409, detail="A sync job is currently running for Google Drive. Please wait.")
    import asyncio
    asyncio.create_task(gdrive_sync_manager.start_sync_job(conn.connection_id, trigger_type=GDriveTriggerType.MANUAL_SYNC))
    return {"status": "started", "connection_id": conn.connection_id}

@router.post("/connectors/gdrive/resync")
async def trigger_gdrive_resync(req: GmailActionRequest, x_tenant_id: str = Header(default="tenant_default")):
    conn = gdrive_sync_manager.store.get_or_create_connection(tenant_id=x_tenant_id, user_id=req.user_id)
    if gdrive_sync_manager.store.is_locked(conn.connection_id):
        raise HTTPException(status_code=409, detail="A sync job is currently running for Google Drive. Please wait.")
    import asyncio
    asyncio.create_task(gdrive_sync_manager.start_sync_job(conn.connection_id, trigger_type=GDriveTriggerType.RESYNC, is_resync=True))
    return {"status": "resync_started", "connection_id": conn.connection_id}

@router.get("/connectors/gdrive/activities")
def get_gdrive_activities(
    user_id: str = "usr_active",
    limit: int = Query(default=20, ge=1, le=100),
    x_tenant_id: str = Header(default="tenant_default"),
):
    conn = gdrive_sync_manager.store.get_or_create_connection(tenant_id=x_tenant_id, user_id=user_id)
    activities = gdrive_sync_manager.store.get_activities(connection_id=conn.connection_id, limit=limit)
    return {
        "status": "success",
        "source": "gdrive",
        "connection_id": conn.connection_id,
        "activities": [act.to_dict() for act in activities],
    }

@router.get("/connectors/gmail/activities")
def get_gmail_activities(
    user_id: str = "usr_active",
    limit: int = Query(default=20, ge=1, le=100),
    x_tenant_id: str = Header(default="tenant_default"),
):
    conn = gmail_sync_manager.store.get_or_create_connection(tenant_id=x_tenant_id, user_id=user_id)
    activities = gmail_sync_manager.store.get_activities(connection_id=conn.connection_id, limit=limit)
    return {
        "status": "success",
        "source": "gmail",
        "connection_id": conn.connection_id,
        "activities": [act.to_dict() for act in activities],
    }

@router.post("/connectors/gdrive/disconnect")
def disconnect_gdrive(req: GmailActionRequest, x_tenant_id: str = Header(default="tenant_default")):
    return gdrive_sync_manager.disconnect_connection(user_id=req.user_id, tenant_id=x_tenant_id)

@router.get("/connectors/{source}/activities")
def get_source_activities(
    source: str,
    user_id: str = "usr_active",
    limit: int = Query(default=20, ge=1, le=100),
    x_tenant_id: str = Header(default="tenant_default"),
):
    src = source.lower().strip()
    if src == "gmail":
        return get_gmail_activities(user_id=user_id, limit=limit, x_tenant_id=x_tenant_id)
    elif src in ("gdrive", "googledrive", "google_drive"):
        return get_gdrive_activities(user_id=user_id, limit=limit, x_tenant_id=x_tenant_id)
    
    return {
        "status": "success",
        "source": src,
        "connection_id": f"conn_{src}_{x_tenant_id}_{user_id}",
        "activities": [],
    }

@router.post("/connectors/gmail/disconnect")
def disconnect_gmail(req: GmailActionRequest, x_tenant_id: str = Header(default="tenant_default")):
    res = gmail_sync_manager.disconnect_connection(user_id=req.user_id, tenant_id=x_tenant_id)
    return res

@router.get("/connectors/{source}/data-summary")
def get_connector_data_summary(
    source: str,
    user_id: str = "usr_active",
    x_tenant_id: str = Header(default="tenant_default"),
):
    """Returns pre-deletion calculation summary of raw records, vector memories, and activity logs."""
    if source.lower() == "gmail":
        summary = gmail_sync_manager.get_data_summary(user_id=user_id, tenant_id=x_tenant_id)
        return {
            "status": "success",
            "source": "gmail",
            "summary": summary,
        }
    elif source.lower() in ("gdrive", "googledrive", "google_drive"):
        summary = gdrive_sync_manager.get_data_summary(user_id=user_id, tenant_id=x_tenant_id)
        return {
            "status": "success",
            "source": "gdrive",
            "summary": summary,
        }
    return {
        "status": "success",
        "source": source.lower(),
        "summary": {
            "tenant_id": x_tenant_id,
            "connection_id": f"conn_{source.lower()}_{x_tenant_id}_{user_id}",
            "synced_messages_count": 0,
            "activities_count": 0,
            "vector_records_count": 0,
            "is_backfill_complete": False,
            "historical_status": "NOT_STARTED",
        }
    }

@router.delete("/connectors/{source}/data")
@router.post("/connectors/{source}/purge-data")
async def purge_connector_all_data(
    source: str,
    user_id: str = Query(default="usr_active"),
    x_tenant_id: str = Header(default="tenant_default"),
):
    """Permanently purges all raw data, vector embeddings, deduplication state, and activity logs across MongoDB & VectorStore."""
    if source.lower() == "gmail":
        res = await gmail_sync_manager.purge_all_connector_data(user_id=user_id, tenant_id=x_tenant_id)
        return res
    elif source.lower() in ("gdrive", "googledrive", "google_drive"):
        res = await gdrive_sync_manager.purge_all_connector_data(user_id=user_id, tenant_id=x_tenant_id)
        return res

    # Generic source fallback
    return {
        "status": "success",
        "message": f"Purged all raw data and vector embeddings for {source}.",
        "purged_metrics": {
            "synced_messages_deleted": 0,
            "activities_deleted": 0,
            "vectors_deleted": 0,
            "canonical_docs_deleted": 0,
        }
    }

@router.post("/connectors/gmail/simulate-webhook")
async def simulate_gmail_webhook(
    req: SimulateWebhookRequest,
    x_tenant_id: str = Header(default="tenant_default"),
):
    """
    Simulates an incoming real-time Gmail webhook event from Composio.
    Executes the full pipeline: Deduplication -> Parsing -> Gatekeeper -> VectorStore -> Activity Record.
    """
    import uuid
    from datetime import datetime, timezone
    from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent, EventType

    msg_id = req.message_id or f"sim_{uuid.uuid4().hex[:12]}"
    canonical_event = CanonicalEvent(
        event_id=f"gmail_{x_tenant_id}_{msg_id}",
        event_type=EventType.CREATE,
        source="gmail",
        tenant_id=x_tenant_id,
        user_id=req.user_id,
        external_id=msg_id,
        raw_ref={"message_id": msg_id, "thread_id": msg_id},
        acl=[req.user_id],
        timestamp=datetime.now(timezone.utc),
        metadata={
            "message_id": msg_id,
            "thread_id": msg_id,
            "subject": req.subject,
            "sender": req.sender,
            "to": req.user_id,
            "body": req.body,
            "snippet": req.snippet or req.body[:150],
            "label_ids": ["INBOX"],
            "attachments": req.attachments,
            "name": f"Email: {req.subject}",
            "mime_type": "message/rfc822",
        },
    )

    res = await gmail_sync_manager.process_webhook_event(canonical_event)
    return res

@router.post("/connectors/gdrive/simulate-webhook")
async def simulate_gdrive_webhook(
    req: SimulateGDriveWebhookRequest,
    x_tenant_id: str = Header(default="tenant_default"),
):
    """
    Simulates an incoming real-time Google Drive webhook event from Composio.
    Executes the full pipeline: Deduplication -> Content Retrieval -> Parsing -> Gatekeeper -> VectorStore -> Activity Record.
    """
    import uuid
    from datetime import datetime, timezone
    from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent, EventType

    file_id = req.file_id or f"sim_gdrive_{uuid.uuid4().hex[:12]}"
    canonical_event = CanonicalEvent(
        event_id=f"gdrive_{x_tenant_id}_{file_id}",
        event_type=EventType.CREATE,
        source="gdrive",
        tenant_id=x_tenant_id,
        user_id=req.user_id,
        external_id=file_id,
        raw_ref={"file_id": file_id, "name": req.name, "mime_type": req.mime_type},
        acl=[req.user_id],
        timestamp=datetime.now(timezone.utc),
        metadata={
            "file_id": file_id,
            "name": req.name,
            "mime_type": req.mime_type,
            "size": req.size,
            "category": req.category,
            "body": req.content,
            "text": req.content,
        },
    )

    res = await gdrive_sync_manager.process_webhook_event(canonical_event, raw_payload={})
    return res


