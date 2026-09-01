from datetime import datetime, timezone
from typing import Any
from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent, EventType

def normalize_gmail(payload: dict[str, Any], tenant_id: str = "tenant_default") -> CanonicalEvent:
    """
    Normalizes incoming Gmail payload (Composio webhook trigger or REST API backfill item)
    into a standardized CanonicalEvent.
    """
    # Check if payload follows Composio structure {metadata, data} or direct Gmail message structure
    meta = payload.get("metadata", {})
    data = payload.get("data", payload)

    message_id = (
        data.get("message_id")
        or data.get("id")
        or meta.get("message_id")
        or meta.get("log_id")
        or "unknown_msg_id"
    )
    thread_id = data.get("thread_id") or data.get("threadId") or message_id
    user_id = meta.get("user_id") or data.get("user_id") or "usr_active"
    connected_account_id = meta.get("connected_account_id") or data.get("connected_account_id", "")

    owner = _extract_owner(data)
    acl = [owner] if owner else [user_id]

    # Extract body / snippet
    body_text = (
        data.get("body")
        or data.get("text")
        or data.get("snippet")
        or data.get("content")
        or ""
    )

    # Extract attachments metadata if provided
    raw_attachments = data.get("attachments", []) or []
    normalized_attachments = []
    for att in raw_attachments:
        if isinstance(att, dict):
            normalized_attachments.append({
                "attachment_id": att.get("attachment_id") or att.get("id") or att.get("filename", ""),
                "filename": att.get("filename") or att.get("name") or "attachment.bin",
                "mime_type": att.get("mime_type") or att.get("mimeType") or "application/octet-stream",
                "size_bytes": int(att.get("size_bytes") or att.get("size") or 0),
                "raw_bytes": att.get("raw_bytes") or att.get("data"),
                "url": att.get("url") or att.get("download_url"),
            })

    timestamp = _parse_ts(data.get("message_timestamp") or data.get("date") or data.get("internalDate"))

    return CanonicalEvent(
        event_id=f"gmail_{tenant_id}_{message_id}",
        event_type=EventType.CREATE,
        source="gmail",
        tenant_id=tenant_id,
        user_id=user_id,
        external_id=str(message_id),
        raw_ref={
            "message_id": message_id,
            "thread_id": thread_id,
            "connected_account_id": connected_account_id,
        },
        acl=acl,
        timestamp=timestamp,
        metadata={
            "subject": data.get("subject", "No Subject"),
            "sender": data.get("sender") or data.get("from", "unknown@sender.com"),
            "to": data.get("to") or data.get("recipient", owner or user_id),
            "body": body_text,
            "snippet": data.get("snippet", ""),
            "label_ids": data.get("label_ids") or data.get("labelIds") or ["INBOX"],
            "thread_id": thread_id,
            "message_id": message_id,
            "received_at": timestamp.isoformat(),
            "attachments": normalized_attachments,
            "name": f"Email: {data.get('subject', 'No Subject')}",
            "mime_type": "message/rfc822",
        },
    )

def _extract_owner(data: dict[str, Any]) -> str | None:
    return data.get("to") or data.get("recipient")

def _parse_ts(raw: Any) -> datetime:
    if not raw:
        return datetime.now(timezone.utc)
    try:
        if isinstance(raw, (int, float)):
            # Handle epoch timestamp (ms or seconds)
            if raw > 1e11:
                return datetime.fromtimestamp(raw / 1000.0, tz=timezone.utc)
            return datetime.fromtimestamp(raw, tz=timezone.utc)
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)
