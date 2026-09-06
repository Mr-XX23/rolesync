from datetime import datetime, timezone
from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent, EventType
from module_1_document_processing.composio_connector.date_utils import normalize_to_utc

def normalize_notion(payload: dict, tenant_id: str) -> CanonicalEvent:
    meta = payload.get("metadata", {})
    data = payload.get("data", {})

    slug = meta.get("trigger_slug", "")
    event_type = EventType.UPDATE
    if "CREATED" in slug or "ADD" in slug:
        event_type = EventType.CREATE
    elif "DELETED" in slug or "ARCHIVED" in slug or data.get("archived"):
        event_type = EventType.DELETE

    page_id = data.get("id") or meta.get("entity_id", "")
    created_by = data.get("created_by", {}).get("id") if isinstance(data.get("created_by"), dict) else None
    
    acl = [created_by] if created_by else [meta.get("user_id", "notion_user")]

    return CanonicalEvent(
        event_id=meta.get("log_id") or page_id,
        event_type=event_type,
        source="notion",
        tenant_id=tenant_id,
        user_id=meta.get("user_id", ""),
        external_id=page_id,
        raw_ref={
            "page_id": page_id,
            "object_type": data.get("object", "page"),
            "connected_account_id": meta.get("connected_account_id"),
        },
        acl=acl,
        timestamp=_parse_ts(data.get("last_edited_time") or data.get("created_time")),
        metadata={
            "title": _extract_notion_title(data),
            "object": data.get("object", "page"),
            "url": data.get("url"),
            "archived": data.get("archived", False),
            "parent": data.get("parent"),
        },
    )

def _extract_notion_title(data: dict) -> str:
    properties = data.get("properties") or {}
    for prop in properties.values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            title_parts = prop.get("title") or []
            return "".join([t.get("plain_text", "") for t in title_parts if isinstance(t, dict)])
    return data.get("title") or "Untitled Notion Document"

def _parse_ts(raw) -> datetime:
    return normalize_to_utc(raw)
