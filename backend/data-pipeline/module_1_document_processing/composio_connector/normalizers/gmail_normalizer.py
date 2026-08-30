from datetime import datetime, timezone
from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent, EventType

def normalize_gmail(payload: dict, tenant_id: str) -> CanonicalEvent:
    """payload = the V3 'payload' object: {metadata, data}."""
    meta = payload["metadata"]
    data = payload["data"]

    owner = _extract_owner(data)  # the mailbox owner = the ACL

    return CanonicalEvent(
        event_id=meta.get("log_id") or data.get("message_id", ""),
        event_type=EventType.CREATE,      # this trigger is new-message only
        source="gmail",
        tenant_id=tenant_id,
        user_id=meta["user_id"],
        external_id=data.get("message_id") or data.get("thread_id", ""),
        raw_ref={
            "message_id": data.get("message_id"),
            "thread_id": data.get("thread_id"),
            "connected_account_id": meta["connected_account_id"],
        },
        acl=[owner] if owner else [meta["user_id"]],
        timestamp=_parse_ts(data.get("message_timestamp")),
        metadata={
            "subject": data.get("subject"),
            "sender": data.get("sender"),
            "label_ids": data.get("label_ids"),
            "thread_id": data.get("thread_id"),
            "message_id": data.get("message_id"),
        },
    )

def _extract_owner(data: dict) -> str | None:
    # gmail new-message payload includes the recipient/owner address
    return data.get("to") or data.get("recipient")


def _parse_ts(raw) -> datetime:
    if not raw:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
