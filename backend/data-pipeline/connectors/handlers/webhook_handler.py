# api/webhook_handler.py
from fastapi import APIRouter, Request
from connectors.connector_service import ConnectorService
# from your pipeline: the Security Scanner is the next stage
# from pipeline.scanner import enqueue_for_scan

router = APIRouter()
connector_service = ConnectorService()


@router.post("/webhooks/composio")
async def composio_webhook(request: Request):
    body = await request.body()          # RAW body — required for signature check
    event = connector_service.handle_webhook(
        body=body,
        headers=request.headers,
        tenant_id="TODO-map-from-user",   # see note below
    )

    if event is None:
        return {"status": "ignored"}      # bad sig raises inside parse; this = unhandled slug

    # Hand the CanonicalEvent to the next module (Security Scanner queue).
    # Return fast — do NOT process inline, or Composio may time out & retry.
    # await enqueue_for_scan(event)
    return {"status": "accepted", "event_id": event.event_id}