from datetime import datetime, timezone
from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent, EventType
from module_1_document_processing.composio_connector.date_utils import normalize_to_utc

def normalize_slack(payload: dict, tenant_id: str) -> CanonicalEvent:
    meta = payload.get("metadata", {})
    data = payload.get("data", {})

    slug = meta.get("trigger_slug", "")
    event_type = EventType.CREATE
    if "DELETED" in slug or "REMOVE" in slug:
        event_type = EventType.DELETE
    elif "UPDATED" in slug or "EDITED" in slug:
        event_type = EventType.UPDATE

    channel_id = data.get("channel") or data.get("channel_id")
    user_id = data.get("user") or data.get("user_id") or meta.get("user_id", "")
    
    # Slack channel membership or direct user scope forms the ACL
    acl = [user_id] if user_id else [meta.get("user_id", "slack_user")]
    if channel_id:
        acl.append(f"channel:{channel_id}")

    ts = data.get("ts") or data.get("event_ts")

    return CanonicalEvent(
        event_id=meta.get("log_id") or f"{channel_id}:{ts}",
        event_type=event_type,
        source="slack",
        tenant_id=tenant_id,
        user_id=user_id,
        external_id=f"{channel_id}:{ts}",
        raw_ref={
            "channel_id": channel_id,
            "message_ts": ts,
            "thread_ts": data.get("thread_ts"),
            "connected_account_id": meta.get("connected_account_id"),
        },
        acl=acl,
        timestamp=_parse_ts(ts),
        metadata={
            "text": data.get("text") or data.get("message", {}).get("text"),
            "channel_id": channel_id,
            "thread_ts": data.get("thread_ts"),
            "user_id": user_id,
            "files": [f.get("id") for f in data.get("files", []) if isinstance(f, dict)],
        },
    )

def _parse_ts(raw) -> datetime:
    return normalize_to_utc(raw)
