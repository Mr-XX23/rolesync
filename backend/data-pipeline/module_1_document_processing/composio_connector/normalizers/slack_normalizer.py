from datetime import datetime, timezone
from typing import Any
from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent, EventType
from module_1_document_processing.composio_connector.date_utils import normalize_to_utc

def normalize_slack(payload: dict[str, Any], tenant_id: str = "tenant_default") -> CanonicalEvent:
    """
    Normalizes Slack payloads across Public Channels, Private Channels, Direct Messages (IM),
    Group Messages (MPIM), and Thread replies into a unified CanonicalEvent.
    """
    meta = payload.get("metadata", {}) if isinstance(payload.get("metadata"), dict) else {}
    data = payload.get("data", {}) if isinstance(payload.get("data"), dict) else {}
    if not data and isinstance(payload.get("payload"), dict):
        data = payload["payload"]

    slug = str(meta.get("trigger_slug") or payload.get("trigger_slug") or "").upper()
    event_type = EventType.CREATE
    if any(k in slug for k in ("DELETED", "REMOVE")):
        event_type = EventType.DELETE
    elif any(k in slug for k in ("UPDATED", "EDITED")):
        event_type = EventType.UPDATE

    channel_id = str(data.get("channel") or data.get("channel_id") or meta.get("channel_id") or "unknown_channel")
    channel_name = str(data.get("channel_name") or meta.get("channel_name") or channel_id)
    sender_id = str(data.get("user") or data.get("user_id") or "")
    sender_name = str(data.get("user_name") or data.get("username") or meta.get("user_name") or sender_id or "slack_user")
    app_user_id = str(meta.get("user_id") or payload.get("user_id") or "")

    # Determine message type (channel, im/dm, mpim/group)
    message_type = "public_channel"
    if channel_id.startswith("D") or "DIRECT" in slug or "IM" in slug or data.get("is_im"):
        message_type = "im"
    elif channel_id.startswith("G") or "GROUP" in slug or "MPIM" in slug or data.get("is_mpim"):
        message_type = "mpim"
    elif data.get("is_private") or channel_id.startswith("C") is False:
        message_type = "private_channel"

    # ACL determination
    acl = [sender_id] if sender_id else ["slack_user"]
    if app_user_id and app_user_id not in acl:
        acl.append(app_user_id)
    if message_type in ("im", "mpim"):
        # For DMs/group chats, include recipient/channel members
        recipients = data.get("recipients", []) or data.get("members", [])
        for r in recipients:
            if isinstance(r, str) and r not in acl:
                acl.append(r)
    else:
        acl.append(f"channel:{channel_id}")

    ts = str(data.get("ts") or data.get("event_ts") or data.get("message_ts") or datetime.now(timezone.utc).timestamp())
    thread_ts = data.get("thread_ts")

    # Extract text content
    text = (
        data.get("text")
        or data.get("message", {}).get("text")
        or data.get("body")
        or ""
    )

    # Attachments and files
    raw_files = data.get("files", []) or []
    files = []
    for f in raw_files:
        if isinstance(f, dict):
            files.append({
                "file_id": f.get("id", ""),
                "name": f.get("name") or f.get("title") or "slack_attachment",
                "mime_type": f.get("mimetype") or f.get("mime_type", "application/octet-stream"),
                "size_bytes": int(f.get("size") or f.get("size_bytes", 0)),
                "url": f.get("url_private_download") or f.get("url_private") or f.get("permalink", ""),
                "raw_bytes": f.get("raw_bytes"),
            })

    unique_ext_id = f"{channel_id}:{ts}"

    return CanonicalEvent(
        event_id=meta.get("log_id") or unique_ext_id,
        event_type=event_type,
        source="slack",
        tenant_id=tenant_id,
        user_id=app_user_id,
        external_id=unique_ext_id,
        raw_ref={
            "channel_id": channel_id,
            "channel_name": channel_name,
            "message_ts": ts,
            "thread_ts": thread_ts,
            "message_type": message_type,
            "connected_account_id": meta.get("connected_account_id"),
            "trigger_id": meta.get("trigger_id") or payload.get("trigger_id"),
        },
        acl=acl,
        timestamp=_parse_ts(ts),
        metadata={
            "channel_id": channel_id,
            "channel_name": channel_name,
            "message_type": message_type,
            "sender_id": sender_id,
            "sender_name": sender_name,
            "text": text,
            "thread_ts": thread_ts,
            "files": files,
            "subject": f"#{channel_name} - {sender_name}",
            "name": f"Slack Message #{channel_name}: {text[:60]}",
        },
    )

def _parse_ts(raw: Any) -> datetime:
    return normalize_to_utc(raw)
