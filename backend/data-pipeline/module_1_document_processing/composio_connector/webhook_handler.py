from fastapi import APIRouter, Request, HTTPException
from typing import Any
from module_1_document_processing.composio_connector.event_router import EventRouter
from module_1_document_processing.pipeline.queue_worker import QueueWorker
from module_1_document_processing.composio_connector.gmail_store import GmailStore
from module_1_document_processing.composio_connector.gmail_models import SyncedMessageRecord

router = APIRouter(tags=["Webhooks"])
event_router = EventRouter()
queue_worker = QueueWorker()
gmail_store = GmailStore()

@router.post("/webhooks/composio")
async def composio_webhook_handler(request: Request):
    payload = await request.json()
    tenant_id = request.headers.get("X-Tenant-ID", "tenant_default")

    canonical_event = event_router.route_payload(payload=payload, tenant_id=tenant_id)
    if not canonical_event:
        return {"status": "ignored", "reason": "Unrecognized trigger or unhandled source"}

    # Deduplication Guard for Gmail
    if canonical_event.source.lower() == "gmail":
        conn_id = canonical_event.raw_ref.get("connected_account_id") or f"conn_gmail_{tenant_id}_{canonical_event.user_id}"
        msg_id = canonical_event.external_id
        if gmail_store.is_message_synced(tenant_id=tenant_id, connection_id=conn_id, message_id=msg_id):
            print(f"[WebhookHandler] Gmail message {msg_id} already synced. Ignoring duplicate webhook event.")
            return {"status": "ignored", "reason": "Duplicate message (already indexed)", "message_id": msg_id}

    await queue_worker.enqueue(canonical_event)
    return {"status": "enqueued", "event_id": canonical_event.event_id, "source": canonical_event.source}
