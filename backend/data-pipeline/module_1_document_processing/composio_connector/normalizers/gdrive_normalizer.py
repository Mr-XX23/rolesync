from datetime import datetime, timezone
from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent, EventType
from module_1_document_processing.composio_connector.date_utils import normalize_to_utc

def normalize_gdrive(payload: dict, tenant_id: str = "tenant_default") -> CanonicalEvent:
    meta = payload.get("metadata", {}) if isinstance(payload.get("metadata"), dict) else {}
    inner_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
    data_payload = payload.get("data") if isinstance(payload.get("data"), dict) else {}

    # Find the deepest file dictionary if nested (Composio file_created or Google Drive changes)
    file_dict = None
    if isinstance(inner_payload.get("file"), dict):
        file_dict = inner_payload["file"]
    elif isinstance(payload.get("file"), dict):
        file_dict = payload["file"]
    elif isinstance(data_payload.get("file"), dict):
        file_dict = data_payload["file"]
    elif isinstance(data_payload.get("data"), dict) and isinstance(data_payload["data"].get("file"), dict):
        file_dict = data_payload["data"]["file"]

    # Target dict where file properties live
    data = file_dict or data_payload or inner_payload or payload
    if not isinstance(data, dict):
        data = {}

    slug = str(
        meta.get("trigger_slug", "")
        or payload.get("trigger_slug", "")
        or payload.get("trigger_name", "")
        or inner_payload.get("event_type", "")
        or payload.get("event_type", "")
        or ""
    ).upper()

    # Determine event type
    is_deleted = (
        payload.get("removed") is True
        or inner_payload.get("removed") is True
        or data.get("trashed") is True
        or inner_payload.get("event_type") in ("trashed", "removed", "file_deleted")
        or payload.get("event_type") in ("trashed", "removed", "file_deleted")
        or "DELETE" in slug
        or "TRASH" in slug
        or "REMOVE" in slug
    )

    if is_deleted:
        event_type = EventType.DELETE
    elif "CREATED" in slug or "ADD" in slug or inner_payload.get("event_type") == "file_created" or payload.get("event_type") == "file_created":
        event_type = EventType.CREATE
    elif "PERMISSION" in slug or "ACL" in slug:
        event_type = EventType.ACL_CHANGE
    else:
        event_type = EventType.UPDATE

    file_id = (
        data.get("id")
        or data.get("fileId")
        or data.get("file_id")
        or (file_dict.get("id") if file_dict else None)
        or inner_payload.get("file_id")
        or inner_payload.get("fileId")
        or payload.get("file_id")
        or payload.get("fileId")
        or ""
    )

    user_id = (
        meta.get("user_id")
        or payload.get("user_id")
        or inner_payload.get("user_id")
        or data.get("user_id")
        or payload.get("userId")
        or meta.get("userId")
        or payload.get("entity_id")
        or meta.get("entity_id")
        or ""
    )

    permissions = data.get("permissions") or inner_payload.get("permissions") or []
    acl = [p.get("emailAddress") for p in permissions if isinstance(p, dict) and p.get("emailAddress")]
    if not acl and user_id:
        acl = [user_id]

    owners_raw = data.get("owners") or inner_payload.get("owners") or []
    owners = [owner.get("emailAddress") for owner in owners_raw if isinstance(owner, dict) and owner.get("emailAddress")]

    ts_raw = (
        data.get("modifiedTime")
        or data.get("createdTime")
        or inner_payload.get("modified_time")
        or inner_payload.get("deletion_timestamp")
        or meta.get("timestamp")
    )

    event_id = (
        meta.get("log_id")
        or payload.get("id")
        or f"gdrive_{tenant_id}_{file_id}"
    )

    filename = data.get("name") or data.get("title") or inner_payload.get("name") or "Untitled Document"
    mime_type = data.get("mimeType") or inner_payload.get("mimeType") or "application/octet-stream"
    file_size = int(data.get("size") or inner_payload.get("size") or 0)
    web_view_link = data.get("webViewLink") or inner_payload.get("webViewLink") or ""

    return CanonicalEvent(
        event_id=event_id,
        event_type=event_type,
        source="gdrive",
        tenant_id=tenant_id,
        user_id=user_id,
        external_id=file_id,
        raw_ref={
            "file_id": file_id,
            "mime_type": mime_type,
            "connected_account_id": meta.get("connected_account_id") or payload.get("connected_account_id") or payload.get("connectedAccountId"),
        },
        acl=acl,
        timestamp=_parse_ts(ts_raw),
        metadata={
            "name": filename,
            "mime_type": mime_type,
            "file_size": file_size,
            "web_view_link": web_view_link,
            "owners": owners,
        },
    )

def _parse_ts(raw) -> datetime:
    return normalize_to_utc(raw)
