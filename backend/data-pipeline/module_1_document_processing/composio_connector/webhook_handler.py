from fastapi import APIRouter, Request, HTTPException
from typing import Any
from module_1_document_processing.composio_connector.event_router import EventRouter
from module_1_document_processing.pipeline.queue_worker import QueueWorker
from module_1_document_processing.composio_connector.gmail_store import GmailStore
from module_1_document_processing.composio_connector.composio_client import ComposioClient
from module_1_document_processing.composio_connector.connector_routes import (
    gmail_sync_manager,
    gdrive_sync_manager,
    calendar_sync_manager,
    slack_sync_manager,
    notion_sync_manager,
)

router = APIRouter(tags=["Webhooks"])
event_router = EventRouter()
queue_worker = QueueWorker()
gmail_store = GmailStore()
composio_client = ComposioClient()

@router.post("/webhooks/composio")
async def composio_webhook_handler(request: Request):
    raw_body = await request.body()
    headers = dict(request.headers)
    tenant_id = headers.get("x-tenant-id", "tenant_default")

    # 1. Parse and verify webhook signature (handles V1, V2, V3 and unverified payloads gracefully)
    success, payload = composio_client.parse_and_verify_webhook(body_bytes=raw_body, headers=headers)
    if not success or not payload:
        raise HTTPException(status_code=400, detail="Invalid webhook payload or signature verification failed")

    # 2. Route payload into CanonicalEvent
    canonical_event = event_router.route_payload(payload=payload, tenant_id=tenant_id)
    if not canonical_event:
        print(f"[WebhookHandler] Ignored unrecognized trigger or unhandled source. Payload keys: {list(payload.keys())}")
        return {"status": "ignored", "reason": "Unrecognized trigger or unhandled source"}

    # 3. For Gmail, process directly via GmailSyncManager to record activity & update watermarks
    if canonical_event.source.lower() == "gmail":
        result = await gmail_sync_manager.process_webhook_event(canonical_event, raw_payload=payload)
        return result

    # 4. For GDrive, process directly via GDriveSyncManager to download content, deduplicate & update watermarks
    if canonical_event.source.lower() in ("gdrive", "googledrive"):
        result = await gdrive_sync_manager.process_webhook_event(canonical_event, raw_payload=payload)
        return result

    # 5. For Calendar, process directly via CalendarSyncManager to format meeting notes, deduplicate & update watermarks
    if canonical_event.source.lower() in ("google_calendar", "calendar", "googlecalendar"):
        result = await calendar_sync_manager.process_webhook_event(canonical_event, raw_payload=payload)
        return result

    # 6. For Slack, process directly via SlackSyncManager to record activity, DMs, channels & update watermarks
    if canonical_event.source.lower() == "slack":
        result = await slack_sync_manager.process_webhook_event(canonical_event, raw_payload=payload)
        return result

    # 7. For Notion, process directly via NotionSyncManager to record pages, databases, blocks & update watermarks
    if canonical_event.source.lower() == "notion":
        result = await notion_sync_manager.process_webhook_event(canonical_event, raw_payload=payload)
        return result

    # 8. For other fallback sources, enqueue to QueueWorker
    await queue_worker.enqueue(canonical_event)
    return {"status": "enqueued", "event_id": canonical_event.event_id, "source": canonical_event.source}



