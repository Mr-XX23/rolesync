from fastapi import APIRouter, Request, HTTPException
from typing import Any
from module_1_document_processing.composio_connector.event_router import EventRouter
from module_1_document_processing.pipeline.queue_worker import QueueWorker

router = APIRouter(tags=["Webhooks"])
event_router = EventRouter()
queue_worker = QueueWorker()

@router.post("/webhooks/composio")
async def composio_webhook_handler(request: Request):
    payload = await request.json()
    tenant_id = request.headers.get("X-Tenant-ID", "tenant_default")

    canonical_event = event_router.route_payload(payload=payload, tenant_id=tenant_id)
    if not canonical_event:
        return {"status": "ignored", "reason": "Unrecognized trigger or unhandled source"}

    await queue_worker.enqueue(canonical_event)
    return {"status": "enqueued", "event_id": canonical_event.event_id, "source": canonical_event.source}
