from datetime import datetime, timezone
from typing import Any
from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent, EventType
from module_1_document_processing.composio_connector.date_utils import normalize_to_utc

def normalize_notion(payload: dict[str, Any], tenant_id: str = "tenant_default") -> CanonicalEvent:
    """
    Normalizes Notion payloads across Pages, Databases, Content Blocks, and Comments into a unified CanonicalEvent.
    """
    meta = payload.get("metadata", {}) if isinstance(payload.get("metadata"), dict) else {}
    data = payload.get("data", {}) if isinstance(payload.get("data"), dict) else {}
    if not data and isinstance(payload.get("payload"), dict):
        data = payload["payload"]

    slug = str(meta.get("trigger_slug") or payload.get("trigger_slug") or "").upper()
    event_type = EventType.UPDATE
    if any(k in slug for k in ("CREATED", "ADD")):
        event_type = EventType.CREATE
    elif any(k in slug for k in ("DELETED", "ARCHIVED", "REMOVE")) or data.get("archived"):
        event_type = EventType.DELETE

    record_id = str(data.get("id") or meta.get("entity_id") or data.get("page_id") or data.get("database_id") or "unknown_notion_id")
    object_type = str(data.get("object") or meta.get("object") or "page").lower()

    created_by = None
    if isinstance(data.get("created_by"), dict):
        created_by = data["created_by"].get("id")

    app_user_id = str(meta.get("user_id") or payload.get("user_id") or "")
    acl = [app_user_id] if app_user_id else ["notion_user"]
    if created_by and created_by not in acl:
        acl.append(created_by)

    title = _extract_notion_title(data, object_type)
    content_text = _extract_notion_content(data, object_type)

    raw_ts = data.get("last_edited_time") or data.get("created_time") or meta.get("timestamp")
    timestamp = normalize_to_utc(raw_ts)

    url = data.get("url") or f"https://notion.so/{record_id.replace('-', '')}"

    return CanonicalEvent(
        event_id=meta.get("log_id") or record_id,
        event_type=event_type,
        source="notion",
        tenant_id=tenant_id,
        user_id=app_user_id,
        external_id=record_id,
        raw_ref={
            "record_id": record_id,
            "object_type": object_type,
            "connected_account_id": meta.get("connected_account_id"),
            "trigger_id": meta.get("trigger_id") or payload.get("trigger_id"),
            "url": url,
        },
        acl=acl,
        timestamp=timestamp,
        metadata={
            "record_id": record_id,
            "object_type": object_type,
            "title": title,
            "url": url,
            "archived": bool(data.get("archived", False)),
            "parent": data.get("parent"),
            "text": content_text,
            "body": content_text,
            "subject": f"Notion [{object_type.upper()}]: {title}",
            "name": f"Notion {object_type.capitalize()}: {title}",
        },
    )

def _extract_notion_title(data: dict[str, Any], object_type: str) -> str:
    # 1. Direct title string
    if isinstance(data.get("title"), str) and data["title"]:
        return data["title"]

    # 2. Database title array
    if isinstance(data.get("title"), list):
        parts = [t.get("plain_text", "") for t in data["title"] if isinstance(t, dict)]
        res = "".join(parts).strip()
        if res:
            return res

    # 3. Page properties title
    properties = data.get("properties") or {}
    if isinstance(properties, dict):
        for prop in properties.values():
            if isinstance(prop, dict) and prop.get("type") == "title":
                title_parts = prop.get("title") or []
                res = "".join([t.get("plain_text", "") for t in title_parts if isinstance(t, dict)]).strip()
                if res:
                    return res

        # Check Name property
        name_prop = properties.get("Name") or properties.get("title")
        if isinstance(name_prop, dict):
            title_parts = name_prop.get("title") or []
            res = "".join([t.get("plain_text", "") for t in title_parts if isinstance(t, dict)]).strip()
            if res:
                return res

    # 4. Fallback for comments or blocks
    if object_type == "comment":
        rich_text = data.get("rich_text") or []
        comment_body = "".join([t.get("plain_text", "") for t in rich_text if isinstance(t, dict)]).strip()
        if comment_body:
            return f"Comment: {comment_body[:50]}"
        return "Notion Discussion Comment"

    return f"Untitled Notion {object_type.capitalize()}"

def _extract_notion_content(data: dict[str, Any], object_type: str) -> str:
    lines = []
    title = _extract_notion_title(data, object_type)
    lines.append(f"# {title}")

    # Properties
    properties = data.get("properties") or {}
    if isinstance(properties, dict):
        for prop_name, prop_val in properties.items():
            if isinstance(prop_val, dict):
                p_type = prop_val.get("type", "")
                if p_type == "select" and isinstance(prop_val.get("select"), dict):
                    lines.append(f"- **{prop_name}**: {prop_val['select'].get('name', '')}")
                elif p_type == "multi_select" and isinstance(prop_val.get("multi_select"), list):
                    names = [s.get("name", "") for s in prop_val["multi_select"] if isinstance(s, dict)]
                    lines.append(f"- **{prop_name}**: {', '.join(names)}")
                elif p_type == "rich_text" and isinstance(prop_val.get("rich_text"), list):
                    texts = [t.get("plain_text", "") for t in prop_val["rich_text"] if isinstance(t, dict)]
                    lines.append(f"- **{prop_name}**: {''.join(texts)}")
                elif p_type == "status" and isinstance(prop_val.get("status"), dict):
                    lines.append(f"- **{prop_name}**: {prop_val['status'].get('name', '')}")

    # Body / Markdown / Block text
    if data.get("markdown"):
        lines.append("\n" + str(data["markdown"]))
    elif data.get("content"):
        lines.append("\n" + str(data["content"]))
    elif data.get("text"):
        lines.append("\n" + str(data["text"]))

    # Comment rich text
    if object_type == "comment" and isinstance(data.get("rich_text"), list):
        texts = [t.get("plain_text", "") for t in data["rich_text"] if isinstance(t, dict)]
        lines.append("\n" + "".join(texts))

    return "\n".join(lines).strip()
