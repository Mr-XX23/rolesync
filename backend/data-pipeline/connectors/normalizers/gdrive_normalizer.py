from datetime import datetime, timezone
from connectors.events.canonical_event import CanonicalEvent, EventType

def normalize_gdrive(payload: dict, tenant_id: str) -> CanonicalEvent:
    meta = payload.get("metadata", {})
    data = payload.get("data", {})

    slug = meta.get("trigger_slug", "")
    event_type = EventType.UPDATE
    if "CREATED" in slug or "ADD" in slug:
        event_type = EventType.CREATE
    elif "DELETED" in slug or "REMOVE" in slug:
        event_type = EventType.DELETE
    elif "PERMISSION" in slug or "ACL" in slug:
        event_type = EventType.ACL_CHANGE

    permissions = data.get("permissions") or []
    acl = [p.get("emailAddress") for p in permissions if isinstance(p, dict) and p.get("emailAddress")]
    if not acl:
        acl = [meta.get("user_id", "owner")]

    return CanonicalEvent(
        event_id=meta.get("log_id") or data.get("id", ""),
        event_type=event_type,
        source="gdrive",
        tenant_id=tenant_id,
        user_id=meta.get("user_id", ""),
        external_id=data.get("id") or data.get("fileId", ""),
        raw_ref={
            "file_id": data.get("id") or data.get("fileId"),
            "mime_type": data.get("mimeType"),
            "connected_account_id": meta.get("connected_account_id"),
        },
        acl=acl,
        timestamp=_parse_ts(data.get("modifiedTime") or data.get("createdTime")),
        metadata={
            "name": data.get("name") or data.get("title"),
            "mime_type": data.get("mimeType"),
            "file_size": data.get("size"),
            "web_view_link": data.get("webViewLink"),
            "owners": [owner.get("emailAddress") for owner in data.get("owners", []) if isinstance(owner, dict)],
        },
    )

def _parse_ts(raw) -> datetime:
    if not raw:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
