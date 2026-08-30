from fastapi import APIRouter, Request
from connectors.connector_service import ConnectorService
from pipeline.queue_worker import QueueWorker

router = APIRouter()
connector_service = ConnectorService()
queue_worker = QueueWorker()

@router.post("/webhooks/composio")
async def composio_webhook(request: Request):
    body = await request.body()  # RAW body — required for signature check
    event = connector_service.handle_webhook(
        body=body,
        headers=request.headers,
        tenant_id="tenant_default",
    )

    if event is None:
        return {"status": "ignored"}

    # Hand the CanonicalEvent to the async Security Scanner & Queue Worker.
    # Returns fast (< 200ms) to ensure Composio webhook doesn't time out.
    await queue_worker.enqueue(event)
    return {"status": "accepted", "event_id": event.event_id}