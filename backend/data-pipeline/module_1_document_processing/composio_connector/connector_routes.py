from fastapi import APIRouter, HTTPException, Query, Header, Depends
from pydantic import BaseModel, Field
from typing import Any
from module_1_document_processing.identity import bind_identity, authed_user_id
from module_1_document_processing.composio_connector.connector_service import ConnectorService
from module_1_document_processing.composio_connector.gmail_sync_manager import GmailSyncManager
from module_1_document_processing.composio_connector.gdrive_sync_manager import GDriveSyncManager
from module_1_document_processing.composio_connector.calendar_sync_manager import CalendarSyncManager
from module_1_document_processing.composio_connector.slack_sync_manager import SlackSyncManager
from module_1_document_processing.composio_connector.notion_sync_manager import NotionSyncManager
from module_1_document_processing.composio_connector.gdrive_models import GDriveSyncConfig, GDriveTriggerType
from module_1_document_processing.composio_connector.calendar_models import CalendarSyncConfig, CalendarTriggerType
from module_1_document_processing.composio_connector.slack_models import SlackSyncConfig, SlackTriggerType
from module_1_document_processing.composio_connector.notion_models import NotionSyncConfig, NotionTriggerType
from module_1_document_processing.composio_connector.enterprise_store import EnterpriseStore

# Every connector route requires the gateway-verified identity (X-User-Id) and
# acts only on that user's connected accounts. The client-supplied `user_id`
# field on request models is ignored (see authed_user_id() usage below).
router = APIRouter(tags=["Connectors"], dependencies=[Depends(bind_identity)])
connector_service = ConnectorService()
gmail_sync_manager = GmailSyncManager()
gdrive_sync_manager = GDriveSyncManager()
calendar_sync_manager = CalendarSyncManager()
slack_sync_manager = SlackSyncManager()
notion_sync_manager = NotionSyncManager()
enterprise_store = EnterpriseStore()


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

class CalendarConfigRequest(BaseModel):
    user_id: str = "usr_active"
    max_events_per_sync: int = Field(default=10, ge=1, le=50)
    categories: list[str] = Field(default_factory=lambda: ["PRIMARY"])
    sync_window_days: int = 180
    future_window_days: int = 365
    auto_sync_interval_minutes: int = 0
    sync_frequency: str = "off"
    auto_sync_enabled: bool = False
    webhook_enabled: bool = False

class SlackConfigRequest(BaseModel):
    user_id: str = "usr_active"
    max_messages_per_sync: int = Field(default=15, ge=1, le=30)
    categories: list[str] = Field(default_factory=lambda: ["PUBLIC_CHANNELS", "DIRECT_MESSAGES", "GROUP_MESSAGES"])
    sync_window_days: int = 180
    auto_sync_interval_minutes: int = 0
    sync_frequency: str = "off"
    auto_sync_enabled: bool = False
    webhook_enabled: bool = False

class NotionConfigRequest(BaseModel):
    user_id: str = "usr_active"
    max_records_per_sync: int = Field(default=15, ge=1, le=30)
    categories: list[str] = Field(default_factory=lambda: ["PAGES", "DATABASES"])
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

class SimulateSlackWebhookRequest(BaseModel):
    user_id: str = "usr_active"
    channel_id: str = "C_TEST_GENERAL"
    channel_name: str = "general"
    sender_name: str = "alice_lead"
    text: str = "Real-time Slack notification: Customer requested enterprise quote."
    message_type: str = "public_channel"
    thread_ts: str | None = None
    files: list[dict[str, Any]] = Field(default_factory=list)

class SimulateNotionWebhookRequest(BaseModel):
    user_id: str = "usr_active"
    record_id: str | None = None
    title: str = "Product Roadmap & Architecture RFC"
    object_type: str = "page"
    content: str = "Notion Real-Time Ingestion: Specification document updated with v2 integration schemas."
    url: str | None = None


@router.get("/connectors/status")
def get_all_connectors_status(user_id: str = "usr_active", x_tenant_id: str = Header(default="tenant_default")):
    """Production endpoint returning live OAuth connectivity, sync metrics, and parameters for all 5 connectors."""
    gmail_conn = gmail_sync_manager.get_connection_status(user_id=authed_user_id(), tenant_id=x_tenant_id)
    gdrive_conn = gdrive_sync_manager.get_connection_status(user_id=authed_user_id(), tenant_id=x_tenant_id)
    cal_conn = calendar_sync_manager.get_connection_status(user_id=authed_user_id(), tenant_id=x_tenant_id)
    slack_conn = slack_sync_manager.get_connection_status(user_id=authed_user_id(), tenant_id=x_tenant_id)
    notion_conn = notion_sync_manager.get_connection_status(user_id=authed_user_id(), tenant_id=x_tenant_id)

    return {
        "status": "success",
        "connections": {
            "gmail": gmail_conn.to_dict() if hasattr(gmail_conn, "to_dict") else gmail_conn,
            "gdrive": gdrive_conn.to_dict() if hasattr(gdrive_conn, "to_dict") else gdrive_conn,
            "calendar": cal_conn.to_dict() if hasattr(cal_conn, "to_dict") else cal_conn,
            "slack": slack_conn.to_dict() if hasattr(slack_conn, "to_dict") else slack_conn,
            "notion": notion_conn.to_dict() if hasattr(notion_conn, "to_dict") else notion_conn,
        },
    }

@router.post("/connectors/{source}/connect")
def connect_connector(source: str, req: ConnectRequest, x_tenant_id: str = Header(default="tenant_default")):
    if source.lower() == "gmail":
        return gmail_sync_manager.initiate_oauth_flow(
            user_id=authed_user_id(),
            tenant_id=x_tenant_id,
            callback_url=req.callback_url,
        )
    elif source.lower() in ("gdrive", "googledrive", "google_drive"):
        return gdrive_sync_manager.initiate_oauth_flow(
            user_id=authed_user_id(),
            tenant_id=x_tenant_id,
            callback_url=req.callback_url,
        )
    elif source.lower() in ("calendar", "googlecalendar", "google_calendar"):
        return calendar_sync_manager.initiate_oauth_flow(
            user_id=authed_user_id(),
            tenant_id=x_tenant_id,
            callback_url=req.callback_url,
        )
    elif source.lower() == "slack":
        return slack_sync_manager.initiate_oauth_flow(
            user_id=authed_user_id(),
            tenant_id=x_tenant_id,
            callback_url=req.callback_url,
        )
    elif source.lower() == "notion":
        return notion_sync_manager.initiate_oauth_flow(
            user_id=authed_user_id(),
            tenant_id=x_tenant_id,
            callback_url=req.callback_url,
        )

    res = connector_service.connect_source(
        user_id=authed_user_id(),
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
            return gmail_sync_manager.disconnect_connection(user_id=authed_user_id(), tenant_id=x_tenant_id)
        elif source.lower() in ("gdrive", "googledrive", "google_drive"):
            return gdrive_sync_manager.disconnect_connection(user_id=authed_user_id(), tenant_id=x_tenant_id)
        elif source.lower() in ("calendar", "googlecalendar", "google_calendar"):
            return calendar_sync_manager.disconnect_connection(user_id=authed_user_id(), tenant_id=x_tenant_id)
        elif source.lower() == "slack":
            return slack_sync_manager.disconnect_connection(user_id=authed_user_id(), tenant_id=x_tenant_id)
        elif source.lower() == "notion":
            return notion_sync_manager.disconnect_connection(user_id=authed_user_id(), tenant_id=x_tenant_id)

        # Invalidate and revoke OAuth token in Composio backend
        try:
            connector_service.composio.disconnect_user_account(user_id=authed_user_id(), source=source)
        except Exception as err:
            print(f"[ConnectorRoutes] Error disconnecting {source}: {err}")

        return {
            "status": "success",
            "message": f"{source} disconnected. OAuth tokens invalidated. Synced memories preserved.",
        }
    finally:
        connector_service.composio.clear_cache(authed_user_id())


@router.post("/connectors/gmail/config")
async def save_gmail_config(req: GmailConfigRequest, x_tenant_id: str = Header(default="tenant_default")):
    res = await gmail_sync_manager.save_configuration_and_start_sync(
        user_id=authed_user_id(),
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
        user_id=authed_user_id(),
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
            user_id=authed_user_id(),
            tenant_id=x_tenant_id,
            sync_frequency=req.sync_frequency,
            interval_minutes=req.interval_minutes,
            auto_sync_enabled=req.auto_sync_enabled,
            webhook_enabled=req.webhook_enabled,
        )
    elif source.lower() in ("calendar", "googlecalendar", "google_calendar"):
        return calendar_sync_manager.update_auto_sync_schedule(
            user_id=authed_user_id(),
            tenant_id=x_tenant_id,
            sync_frequency=req.sync_frequency,
            interval_minutes=req.interval_minutes,
            auto_sync_enabled=req.auto_sync_enabled,
            webhook_enabled=req.webhook_enabled,
        )
    elif source.lower() == "slack":
        return slack_sync_manager.update_auto_sync_schedule(
            user_id=authed_user_id(),
            tenant_id=x_tenant_id,
            sync_frequency=req.sync_frequency,
            interval_minutes=req.interval_minutes,
            auto_sync_enabled=req.auto_sync_enabled,
            webhook_enabled=req.webhook_enabled,
        )
    elif source.lower() == "notion":
        return notion_sync_manager.update_auto_sync_schedule(
            user_id=authed_user_id(),
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
    conn_dict = gmail_sync_manager.get_connection_status(user_id=authed_user_id(), tenant_id=x_tenant_id)
    return {
        "status": "success",
        "connection": conn_dict,
    }

@router.post("/connectors/gmail/sync-now")
async def trigger_gmail_sync_now(req: GmailActionRequest, x_tenant_id: str = Header(default="tenant_default")):
    res = await gmail_sync_manager.trigger_manual_sync(user_id=authed_user_id(), tenant_id=x_tenant_id)
    if res.get("status") == "locked":
        raise HTTPException(status_code=409, detail=res.get("message"))
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

@router.post("/connectors/gmail/resync")
async def trigger_gmail_resync(req: GmailActionRequest, x_tenant_id: str = Header(default="tenant_default")):
    res = await gmail_sync_manager.trigger_resync(user_id=authed_user_id(), tenant_id=x_tenant_id)
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
        user_id=authed_user_id(),
        tenant_id=x_tenant_id,
        config=cfg,
    )

@router.post("/connectors/gdrive/auto-sync")
async def update_gdrive_auto_sync(req: AutoSyncScheduleRequest, x_tenant_id: str = Header(default="tenant_default")):
    return gdrive_sync_manager.update_auto_sync_schedule(
        user_id=authed_user_id(),
        tenant_id=x_tenant_id,
        sync_frequency=req.sync_frequency,
        interval_minutes=req.interval_minutes,
        auto_sync_enabled=req.auto_sync_enabled,
        webhook_enabled=req.webhook_enabled,
    )


@router.get("/connectors/gdrive/status")
def get_gdrive_status(user_id: str = "usr_active", x_tenant_id: str = Header(default="tenant_default")):
    conn = gdrive_sync_manager.get_connection_status(user_id=authed_user_id(), tenant_id=x_tenant_id)
    return {
        "status": "success",
        "connection": conn.to_dict(),
    }

@router.post("/connectors/gdrive/sync-now")
async def trigger_gdrive_sync_now(req: GmailActionRequest, x_tenant_id: str = Header(default="tenant_default")):
    conn = gdrive_sync_manager.store.get_or_create_connection(tenant_id=x_tenant_id, user_id=authed_user_id())
    if gdrive_sync_manager.store.is_locked(conn.connection_id):
        raise HTTPException(status_code=409, detail="A sync job is currently running for Google Drive. Please wait.")
    import asyncio
    asyncio.create_task(gdrive_sync_manager.start_sync_job(conn.connection_id, trigger_type=GDriveTriggerType.MANUAL_SYNC))
    return {"status": "started", "connection_id": conn.connection_id}

@router.post("/connectors/gdrive/resync")
async def trigger_gdrive_resync(req: GmailActionRequest, x_tenant_id: str = Header(default="tenant_default")):
    conn = gdrive_sync_manager.store.get_or_create_connection(tenant_id=x_tenant_id, user_id=authed_user_id())
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
    conn = gdrive_sync_manager.store.get_or_create_connection(tenant_id=x_tenant_id, user_id=authed_user_id())
    activities = gdrive_sync_manager.store.get_activities(connection_id=conn.connection_id, limit=limit)
    return {
        "status": "success",
        "source": "gdrive",
        "connection_id": conn.connection_id,
        "activities": [act.to_dict() for act in activities],
    }

# =========================================================================
# Google Calendar Specific Endpoints
# =========================================================================

@router.post("/connectors/calendar/config")
async def save_calendar_config(req: CalendarConfigRequest, x_tenant_id: str = Header(default="tenant_default")):
    cfg = CalendarSyncConfig(
        max_events_per_sync=req.max_events_per_sync,
        categories=req.categories if req.categories else ["PRIMARY"],
        sync_window_days=req.sync_window_days,
        future_window_days=req.future_window_days,
        auto_sync_interval_minutes=req.auto_sync_interval_minutes,
        sync_frequency=req.sync_frequency,
        auto_sync_enabled=req.auto_sync_enabled,
        webhook_enabled=req.webhook_enabled,
    )
    return await calendar_sync_manager.save_configuration_and_start_sync(
        user_id=authed_user_id(),
        tenant_id=x_tenant_id,
        config=cfg,
    )

@router.post("/connectors/calendar/auto-sync")
async def update_calendar_auto_sync(req: AutoSyncScheduleRequest, x_tenant_id: str = Header(default="tenant_default")):
    return calendar_sync_manager.update_auto_sync_schedule(
        user_id=authed_user_id(),
        tenant_id=x_tenant_id,
        sync_frequency=req.sync_frequency,
        interval_minutes=req.interval_minutes,
        auto_sync_enabled=req.auto_sync_enabled,
        webhook_enabled=req.webhook_enabled,
    )

@router.get("/connectors/calendar/status")
def get_calendar_status(user_id: str = "usr_active", x_tenant_id: str = Header(default="tenant_default")):
    conn = calendar_sync_manager.get_connection_status(user_id=authed_user_id(), tenant_id=x_tenant_id)
    return {
        "status": "success",
        "connection": conn.to_dict(),
    }

@router.post("/connectors/calendar/sync-now")
async def trigger_calendar_sync_now(req: GmailActionRequest, x_tenant_id: str = Header(default="tenant_default")):
    conn = calendar_sync_manager.store.get_or_create_connection(tenant_id=x_tenant_id, user_id=authed_user_id())
    if calendar_sync_manager.store.is_locked(conn.connection_id):
        raise HTTPException(status_code=409, detail="A sync job is currently running for Google Calendar. Please wait.")
    import asyncio
    asyncio.create_task(calendar_sync_manager.start_sync_job(conn.connection_id, trigger_type=CalendarTriggerType.MANUAL_SYNC))
    return {"status": "started", "connection_id": conn.connection_id}

@router.post("/connectors/calendar/resync")
async def trigger_calendar_resync(req: GmailActionRequest, x_tenant_id: str = Header(default="tenant_default")):
    conn = calendar_sync_manager.store.get_or_create_connection(tenant_id=x_tenant_id, user_id=authed_user_id())
    if calendar_sync_manager.store.is_locked(conn.connection_id):
        raise HTTPException(status_code=409, detail="A sync job is currently running for Google Calendar. Please wait.")
    import asyncio
    asyncio.create_task(calendar_sync_manager.start_sync_job(conn.connection_id, trigger_type=CalendarTriggerType.RESYNC, is_resync=True))
    return {"status": "resync_started", "connection_id": conn.connection_id}

@router.get("/connectors/calendar/activities")
def get_calendar_activities(
    user_id: str = "usr_active",
    limit: int = Query(default=20, ge=1, le=100),
    x_tenant_id: str = Header(default="tenant_default"),
):
    conn = calendar_sync_manager.store.get_or_create_connection(tenant_id=x_tenant_id, user_id=authed_user_id())
    activities = calendar_sync_manager.store.get_activities(connection_id=conn.connection_id, limit=limit)
    return {
        "status": "success",
        "source": "calendar",
        "connection_id": conn.connection_id,
        "activities": [act.to_dict() for act in activities],
    }

@router.post("/connectors/calendar/disconnect")
def disconnect_calendar(req: GmailActionRequest, x_tenant_id: str = Header(default="tenant_default")):
    return calendar_sync_manager.disconnect_connection(user_id=authed_user_id(), tenant_id=x_tenant_id)

@router.get("/connectors/gmail/activities")
def get_gmail_activities(
    user_id: str = "usr_active",
    limit: int = Query(default=20, ge=1, le=100),
    x_tenant_id: str = Header(default="tenant_default"),
):
    conn = gmail_sync_manager.store.get_or_create_connection(tenant_id=x_tenant_id, user_id=authed_user_id())
    activities = gmail_sync_manager.store.get_activities(connection_id=conn.connection_id, limit=limit)
    return {
        "status": "success",
        "source": "gmail",
        "connection_id": conn.connection_id,
        "activities": [act.to_dict() for act in activities],
    }

@router.post("/connectors/gdrive/disconnect")
def disconnect_gdrive(req: GmailActionRequest, x_tenant_id: str = Header(default="tenant_default")):
    return gdrive_sync_manager.disconnect_connection(user_id=authed_user_id(), tenant_id=x_tenant_id)

@router.get("/connectors/slack/activities")
def get_slack_activities(
    user_id: str = "usr_active",
    limit: int = Query(default=20, ge=1, le=100),
    x_tenant_id: str = Header(default="tenant_default"),
):
    conn = slack_sync_manager.store.get_or_create_connection(tenant_id=x_tenant_id, user_id=authed_user_id())
    activities = slack_sync_manager.store.get_activities(connection_id=conn.connection_id, limit=limit)
    return {
        "status": "success",
        "source": "slack",
        "connection_id": conn.connection_id,
        "activities": [act.to_dict() for act in activities],
    }

@router.get("/connectors/notion/activities")
def get_notion_activities(
    user_id: str = "usr_active",
    limit: int = Query(default=20, ge=1, le=100),
    x_tenant_id: str = Header(default="tenant_default"),
):
    conn = notion_sync_manager.store.get_or_create_connection(tenant_id=x_tenant_id, user_id=authed_user_id())
    activities = notion_sync_manager.store.get_activities(connection_id=conn.connection_id, limit=limit)
    return {
        "status": "success",
        "source": "notion",
        "connection_id": conn.connection_id,
        "activities": [act.to_dict() for act in activities],
    }

@router.get("/connectors/{source}/activities")
def get_source_activities(
    source: str,
    user_id: str = "usr_active",
    limit: int = Query(default=20, ge=1, le=100),
    x_tenant_id: str = Header(default="tenant_default"),
):
    src = source.lower()
    if src == "gmail":
        return get_gmail_activities(user_id=authed_user_id(), limit=limit, x_tenant_id=x_tenant_id)
    elif src in ("gdrive", "googledrive", "google_drive"):
        return get_gdrive_activities(user_id=authed_user_id(), limit=limit, x_tenant_id=x_tenant_id)
    elif src in ("calendar", "googlecalendar", "google_calendar"):
        return get_calendar_activities(user_id=authed_user_id(), limit=limit, x_tenant_id=x_tenant_id)
    elif src == "slack":
        return get_slack_activities(user_id=authed_user_id(), limit=limit, x_tenant_id=x_tenant_id)
    elif src == "notion":
        return get_notion_activities(user_id=authed_user_id(), limit=limit, x_tenant_id=x_tenant_id)
    
    return {
        "status": "success",
        "source": src,
        "connection_id": f"conn_{src}_{x_tenant_id}_{user_id}",
        "activities": [],
    }

# =========================================================================
# Slack Specific Endpoints
# =========================================================================

@router.post("/connectors/slack/config")
async def save_slack_config(req: SlackConfigRequest, x_tenant_id: str = Header(default="tenant_default")):
    cfg = SlackSyncConfig(
        max_messages_per_sync=req.max_messages_per_sync,
        categories=req.categories if req.categories else ["PUBLIC_CHANNELS", "DIRECT_MESSAGES", "GROUP_MESSAGES"],
        sync_window_days=req.sync_window_days,
        auto_sync_interval_minutes=req.auto_sync_interval_minutes,
        sync_frequency=req.sync_frequency,
        auto_sync_enabled=req.auto_sync_enabled,
        webhook_enabled=req.webhook_enabled,
    )
    return await slack_sync_manager.save_configuration_and_start_sync(
        user_id=authed_user_id(),
        tenant_id=x_tenant_id,
        config_data=cfg.to_dict(),
    )

@router.post("/connectors/slack/auto-sync")
async def update_slack_auto_sync(req: AutoSyncScheduleRequest, x_tenant_id: str = Header(default="tenant_default")):
    return slack_sync_manager.update_auto_sync_schedule(
        user_id=authed_user_id(),
        tenant_id=x_tenant_id,
        sync_frequency=req.sync_frequency,
        interval_minutes=req.interval_minutes,
        auto_sync_enabled=req.auto_sync_enabled,
        webhook_enabled=req.webhook_enabled,
    )

@router.get("/connectors/slack/status")
def get_slack_status(user_id: str = "usr_active", x_tenant_id: str = Header(default="tenant_default")):
    conn = slack_sync_manager.get_connection_status(user_id=authed_user_id(), tenant_id=x_tenant_id)
    return {
        "status": "success",
        "connection": conn.to_dict(),
    }

@router.post("/connectors/slack/sync-now")
async def trigger_slack_sync_now(req: GmailActionRequest, x_tenant_id: str = Header(default="tenant_default")):
    conn = slack_sync_manager.store.get_or_create_connection(tenant_id=x_tenant_id, user_id=authed_user_id())
    if slack_sync_manager.store.is_locked(conn.connection_id):
        raise HTTPException(status_code=409, detail="A sync job is currently running for Slack. Please wait.")
    import asyncio
    asyncio.create_task(slack_sync_manager.execute_sync_job(conn.connection_id, trigger_type=SlackTriggerType.MANUAL_SYNC))
    return {"status": "started", "connection_id": conn.connection_id}

@router.post("/connectors/slack/resync")
async def trigger_slack_resync(req: GmailActionRequest, x_tenant_id: str = Header(default="tenant_default")):
    conn = slack_sync_manager.store.get_or_create_connection(tenant_id=x_tenant_id, user_id=authed_user_id())
    if slack_sync_manager.store.is_locked(conn.connection_id):
        raise HTTPException(status_code=409, detail="A sync job is currently running for Slack. Please wait.")
    import asyncio
    asyncio.create_task(slack_sync_manager.execute_sync_job(conn.connection_id, trigger_type=SlackTriggerType.RESYNC, is_resync=True))
    return {"status": "resync_started", "connection_id": conn.connection_id}

@router.post("/connectors/slack/disconnect")
def disconnect_slack(req: GmailActionRequest, x_tenant_id: str = Header(default="tenant_default")):
    return slack_sync_manager.disconnect_connection(user_id=authed_user_id(), tenant_id=x_tenant_id)

# =========================================================================
# Notion Specific Endpoints
# =========================================================================

@router.post("/connectors/notion/config")
async def save_notion_config(req: NotionConfigRequest, x_tenant_id: str = Header(default="tenant_default")):
    cfg = NotionSyncConfig(
        max_records_per_sync=req.max_records_per_sync,
        categories=req.categories if req.categories else ["PAGES", "DATABASES"],
        sync_window_days=req.sync_window_days,
        auto_sync_interval_minutes=req.auto_sync_interval_minutes,
        sync_frequency=req.sync_frequency,
        auto_sync_enabled=req.auto_sync_enabled,
        webhook_enabled=req.webhook_enabled,
    )
    return await notion_sync_manager.save_configuration_and_start_sync(
        user_id=authed_user_id(),
        tenant_id=x_tenant_id,
        config_data=cfg.to_dict(),
    )

@router.post("/connectors/notion/auto-sync")
async def update_notion_auto_sync(req: AutoSyncScheduleRequest, x_tenant_id: str = Header(default="tenant_default")):
    return notion_sync_manager.update_auto_sync_schedule(
        user_id=authed_user_id(),
        tenant_id=x_tenant_id,
        sync_frequency=req.sync_frequency,
        interval_minutes=req.interval_minutes,
        auto_sync_enabled=req.auto_sync_enabled,
        webhook_enabled=req.webhook_enabled,
    )

@router.get("/connectors/notion/status")
def get_notion_status(user_id: str = "usr_active", x_tenant_id: str = Header(default="tenant_default")):
    conn = notion_sync_manager.get_connection_status(user_id=authed_user_id(), tenant_id=x_tenant_id)
    return {
        "status": "success",
        "connection": conn.to_dict(),
    }

@router.post("/connectors/notion/sync-now")
async def trigger_notion_sync_now(req: GmailActionRequest, x_tenant_id: str = Header(default="tenant_default")):
    conn = notion_sync_manager.store.get_or_create_connection(tenant_id=x_tenant_id, user_id=authed_user_id())
    if notion_sync_manager.store.is_locked(conn.connection_id):
        raise HTTPException(status_code=409, detail="A sync job is currently running for Notion. Please wait.")
    import asyncio
    asyncio.create_task(notion_sync_manager.execute_sync_job(conn.connection_id, trigger_type=NotionTriggerType.MANUAL_SYNC))
    return {"status": "started", "connection_id": conn.connection_id}

@router.post("/connectors/notion/resync")
async def trigger_notion_resync(req: GmailActionRequest, x_tenant_id: str = Header(default="tenant_default")):
    conn = notion_sync_manager.store.get_or_create_connection(tenant_id=x_tenant_id, user_id=authed_user_id())
    if notion_sync_manager.store.is_locked(conn.connection_id):
        raise HTTPException(status_code=409, detail="A sync job is currently running for Notion. Please wait.")
    import asyncio
    asyncio.create_task(notion_sync_manager.execute_sync_job(conn.connection_id, trigger_type=NotionTriggerType.RESYNC, is_resync=True))
    return {"status": "resync_started", "connection_id": conn.connection_id}

@router.post("/connectors/notion/disconnect")
def disconnect_notion(req: GmailActionRequest, x_tenant_id: str = Header(default="tenant_default")):
    return notion_sync_manager.disconnect_connection(user_id=authed_user_id(), tenant_id=x_tenant_id)

@router.post("/connectors/gmail/disconnect")
def disconnect_gmail(req: GmailActionRequest, x_tenant_id: str = Header(default="tenant_default")):
    res = gmail_sync_manager.disconnect_connection(user_id=authed_user_id(), tenant_id=x_tenant_id)
    return res

@router.get("/connectors/{source}/data-summary")
def get_connector_data_summary(
    source: str,
    user_id: str = "usr_active",
    x_tenant_id: str = Header(default="tenant_default"),
):
    """Returns pre-deletion calculation summary of raw records, vector memories, and activity logs."""
    src = source.lower()
    if src == "gmail":
        summary = gmail_sync_manager.get_data_summary(user_id=authed_user_id(), tenant_id=x_tenant_id)
        return {"status": "success", "source": "gmail", "summary": summary}
    elif src in ("gdrive", "googledrive", "google_drive"):
        summary = gdrive_sync_manager.get_data_summary(user_id=authed_user_id(), tenant_id=x_tenant_id)
        return {"status": "success", "source": "gdrive", "summary": summary}
    elif src in ("calendar", "googlecalendar", "google_calendar"):
        summary = calendar_sync_manager.get_data_summary(user_id=authed_user_id(), tenant_id=x_tenant_id)
        return {"status": "success", "source": "google_calendar", "summary": summary}
    elif src == "slack":
        summary = slack_sync_manager.get_data_summary(user_id=authed_user_id(), tenant_id=x_tenant_id)
        return {"status": "success", "source": "slack", "summary": summary}
    elif src == "notion":
        summary = notion_sync_manager.get_data_summary(user_id=authed_user_id(), tenant_id=x_tenant_id)
        return {"status": "success", "source": "notion", "summary": summary}

    return {
        "status": "success",
        "source": src,
        "summary": {
            "tenant_id": x_tenant_id,
            "connection_id": f"conn_{src}_{x_tenant_id}_{authed_user_id()}",
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
    src = source.lower()
    if src == "gmail":
        return await gmail_sync_manager.purge_all_connector_data(user_id=authed_user_id(), tenant_id=x_tenant_id)
    elif src in ("gdrive", "googledrive", "google_drive"):
        return await gdrive_sync_manager.purge_all_connector_data(user_id=authed_user_id(), tenant_id=x_tenant_id)
    elif src in ("calendar", "googlecalendar", "google_calendar"):
        return await calendar_sync_manager.purge_all_connector_data(user_id=authed_user_id(), tenant_id=x_tenant_id)
    elif src == "slack":
        return await slack_sync_manager.purge_all_connector_data(user_id=authed_user_id(), tenant_id=x_tenant_id)
    elif src == "notion":
        return await notion_sync_manager.purge_all_connector_data(user_id=authed_user_id(), tenant_id=x_tenant_id)

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

@router.post("/connectors/{source}/retry-failed")
async def retry_failed_items_endpoint(
    source: str,
    req: GmailActionRequest,
    x_tenant_id: str = Header(default="tenant_default"),
):
    """Retries previously failed items for the specified connector without wiping clean memories."""
    src = source.lower()
    if src == "gmail":
        return await gmail_sync_manager.retry_failed_items(user_id=authed_user_id(), tenant_id=x_tenant_id)
    elif src in ("gdrive", "googledrive", "google_drive"):
        return await gdrive_sync_manager.retry_failed_items(user_id=authed_user_id(), tenant_id=x_tenant_id)
    elif src in ("calendar", "googlecalendar", "google_calendar"):
        return await calendar_sync_manager.retry_failed_items(user_id=authed_user_id(), tenant_id=x_tenant_id)
    elif src == "slack":
        return await slack_sync_manager.retry_failed_items(user_id=authed_user_id(), tenant_id=x_tenant_id)
    elif src == "notion":
        return await notion_sync_manager.retry_failed_items(user_id=authed_user_id(), tenant_id=x_tenant_id)
    raise HTTPException(status_code=400, detail=f"Unsupported source for retry: {source}")

@router.post("/connectors/gmail/simulate-webhook")
async def simulate_gmail_webhook(
    req: SimulateWebhookRequest,
    x_tenant_id: str = Header(default="tenant_default"),
):
    import uuid
    from datetime import datetime, timezone
    from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent, EventType

    msg_id = req.message_id or f"sim_{uuid.uuid4().hex[:12]}"
    canonical_event = CanonicalEvent(
        event_id=f"gmail_{x_tenant_id}_{msg_id}",
        event_type=EventType.CREATE,
        source="gmail",
        tenant_id=x_tenant_id,
        user_id=authed_user_id(),
        external_id=msg_id,
        raw_ref={"message_id": msg_id, "thread_id": msg_id},
        acl=[authed_user_id()],
        timestamp=datetime.now(timezone.utc),
        metadata={
            "message_id": msg_id,
            "thread_id": msg_id,
            "subject": req.subject,
            "sender": req.sender,
            "to": authed_user_id(),
            "body": req.body,
            "snippet": req.snippet or req.body[:150],
            "label_ids": ["INBOX"],
            "attachments": req.attachments,
            "name": f"Email: {req.subject}",
            "mime_type": "message/rfc822",
        },
    )
    return await gmail_sync_manager.process_webhook_event(canonical_event)

@router.post("/connectors/gdrive/simulate-webhook")
async def simulate_gdrive_webhook(
    req: SimulateGDriveWebhookRequest,
    x_tenant_id: str = Header(default="tenant_default"),
):
    import uuid
    from datetime import datetime, timezone
    from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent, EventType

    file_id = req.file_id or f"sim_gdrive_{uuid.uuid4().hex[:12]}"
    canonical_event = CanonicalEvent(
        event_id=f"gdrive_{x_tenant_id}_{file_id}",
        event_type=EventType.CREATE,
        source="gdrive",
        tenant_id=x_tenant_id,
        user_id=authed_user_id(),
        external_id=file_id,
        raw_ref={"file_id": file_id, "name": req.name, "mime_type": req.mime_type},
        acl=[authed_user_id()],
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
    return await gdrive_sync_manager.process_webhook_event(canonical_event, raw_payload={})

@router.post("/connectors/slack/simulate-webhook")
async def simulate_slack_webhook(
    req: SimulateSlackWebhookRequest,
    x_tenant_id: str = Header(default="tenant_default"),
):
    """
    Simulates incoming real-time Slack webhook event (DM, group message, or channel message).
    """
    import uuid
    from datetime import datetime, timezone
    from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent, EventType

    ts = str(datetime.now(timezone.utc).timestamp())
    msg_id = f"{req.channel_id}:{ts}"
    canonical_event = CanonicalEvent(
        event_id=f"slack_{x_tenant_id}_{uuid.uuid4().hex[:8]}",
        event_type=EventType.CREATE,
        source="slack",
        tenant_id=x_tenant_id,
        user_id=authed_user_id(),
        external_id=msg_id,
        raw_ref={
            "channel_id": req.channel_id,
            "channel_name": req.channel_name,
            "message_ts": ts,
            "thread_ts": req.thread_ts,
            "message_type": req.message_type,
        },
        acl=[authed_user_id(), f"channel:{req.channel_id}"],
        timestamp=datetime.now(timezone.utc),
        metadata={
            "channel_id": req.channel_id,
            "channel_name": req.channel_name,
            "message_type": req.message_type,
            "sender_id": authed_user_id(),
            "sender_name": req.sender_name,
            "text": req.text,
            "body": req.text,
            "thread_ts": req.thread_ts,
            "files": req.files,
            "subject": f"#{req.channel_name} - {req.sender_name}",
            "name": f"Slack #{req.channel_name}: {req.text[:60]}",
        },
    )
    return await slack_sync_manager.process_webhook_event(canonical_event)

@router.post("/connectors/notion/simulate-webhook")
async def simulate_notion_webhook(
    req: SimulateNotionWebhookRequest,
    x_tenant_id: str = Header(default="tenant_default"),
):
    """
    Simulates incoming real-time Notion webhook event (page update, database update, etc.).
    """
    import uuid
    from datetime import datetime, timezone
    from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent, EventType

    rec_id = req.record_id or f"sim_notion_{uuid.uuid4().hex[:12]}"
    canonical_event = CanonicalEvent(
        event_id=f"notion_{x_tenant_id}_{rec_id}",
        event_type=EventType.CREATE,
        source="notion",
        tenant_id=x_tenant_id,
        user_id=authed_user_id(),
        external_id=rec_id,
        raw_ref={
            "record_id": rec_id,
            "object_type": req.object_type,
            "url": req.url,
        },
        acl=[authed_user_id()],
        timestamp=datetime.now(timezone.utc),
        metadata={
            "record_id": rec_id,
            "object_type": req.object_type,
            "title": req.title,
            "url": req.url or f"https://notion.so/{rec_id}",
            "archived": False,
            "text": req.content,
            "body": req.content,
            "subject": f"Notion [{req.object_type.upper()}]: {req.title}",
            "name": f"Notion {req.object_type.capitalize()}: {req.title}",
        },
    )
    return await notion_sync_manager.process_webhook_event(canonical_event)


class EnterpriseSyncRequest(BaseModel):
    user_id: str = "usr_active"
    database_system: str
    requirements: str
    contact_email: str | None = None


@router.post("/connectors/enterprise-request")
async def request_enterprise_sync(
    req: EnterpriseSyncRequest,
    x_tenant_id: str = Header(default="tenant_default"),
):
    """Logs and queues custom enterprise connector integration request for architectural review."""
    db_system = req.database_system.strip()
    reqs = req.requirements.strip()
    if not db_system or not reqs:
        raise HTTPException(status_code=400, detail="Both target database system and requirements details are required.")

    record = enterprise_store.create_request(
        user_id=authed_user_id(),
        tenant_id=x_tenant_id,
        database_system=db_system,
        requirements=reqs,
        contact_email=req.contact_email,
    )

    return {
        "status": "success",
        "message": f"Enterprise pipeline request for '{db_system}' has been logged and queued for connectivity verification.",
        "request": record,
    }


@router.get("/connectors/enterprise-requests")
async def get_enterprise_sync_requests(
    user_id: str = Query(default="usr_active"),
    x_tenant_id: str = Header(default="tenant_default"),
):
    """Retrieves all submitted enterprise connector requests for the user/tenant."""
    requests = enterprise_store.get_requests(user_id=authed_user_id(), tenant_id=x_tenant_id)
    return {
        "status": "success",
        "requests": requests,
    }


@router.delete("/connectors/enterprise-requests/{request_id}")
async def cancel_enterprise_sync_request(
    request_id: str,
    user_id: str = Query(default="usr_active"),
):
    """Cancels or removes a submitted custom enterprise connector request."""
    success = enterprise_store.cancel_request(request_id=request_id, user_id=authed_user_id())
    return {
        "status": "success",
        "message": f"Enterprise request '{request_id}' has been cancelled.",
        "cancelled": success,
    }
