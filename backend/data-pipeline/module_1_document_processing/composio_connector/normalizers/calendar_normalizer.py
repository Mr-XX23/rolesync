from datetime import datetime, timezone
from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent, EventType
from module_1_document_processing.composio_connector.date_utils import normalize_to_utc

def normalize_calendar(payload: dict, tenant_id: str = "tenant_default") -> CanonicalEvent:
    if not isinstance(payload, dict):
        payload = {}

    meta = payload.get("metadata", {}) if isinstance(payload.get("metadata"), dict) else {}
    inner_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
    data_payload = payload.get("data") if isinstance(payload.get("data"), dict) else {}

    # Target dict where event properties live
    event_dict = None
    for cand in [inner_payload, data_payload, payload]:
        if isinstance(cand.get("event"), dict):
            event_dict = cand["event"]
            break
        if isinstance(cand.get("event_data"), dict):
            event_dict = cand["event_data"]
            break

    data = event_dict or inner_payload or data_payload or payload
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

    event_type_str = str(
        data.get("event_type")
        or inner_payload.get("event_type")
        or payload.get("event_type")
        or ""
    ).lower()

    status_str = str(data.get("status") or inner_payload.get("status") or "").lower()

    # Determine event type
    is_deleted = (
        status_str in ("cancelled", "deleted")
        or event_type_str in ("deleted", "cancelled", "canceled")
        or "DELETED" in slug
        or "CANCEL" in slug
        or "REMOVE" in slug
    )

    if is_deleted:
        event_type = EventType.DELETE
    elif "CREATED" in slug or "ADD" in slug or event_type_str == "created":
        event_type = EventType.CREATE
    else:
        event_type = EventType.UPDATE

    event_id = (
        data.get("id")
        or data.get("event_id")
        or data.get("eventId")
        or inner_payload.get("event_id")
        or inner_payload.get("id")
        or payload.get("event_id")
        or payload.get("id")
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

    attendees_raw = data.get("attendees") or inner_payload.get("attendees") or []
    acl = [a.get("email") for a in attendees_raw if isinstance(a, dict) and a.get("email")]
    creator = data.get("creator_email") or (data.get("creator", {}).get("email") if isinstance(data.get("creator"), dict) else None)
    organizer = data.get("organizer_email") or (data.get("organizer", {}).get("email") if isinstance(data.get("organizer"), dict) else None)
    if creator and creator not in acl:
        acl.append(creator)
    if organizer and organizer not in acl:
        acl.append(organizer)
    if not acl and user_id:
        acl = [user_id]

    # Timing extraction (supports start_time, start.dateTime, start.date)
    start_obj = data.get("start") or inner_payload.get("start") or {}
    end_obj = data.get("end") or inner_payload.get("end") or {}
    start_time = (
        data.get("start_time")
        or inner_payload.get("start_time")
        or (start_obj.get("dateTime") if isinstance(start_obj, dict) else None)
        or (start_obj.get("date") if isinstance(start_obj, dict) else None)
    )
    end_time = (
        data.get("end_time")
        or inner_payload.get("end_time")
        or (end_obj.get("dateTime") if isinstance(end_obj, dict) else None)
        or (end_obj.get("date") if isinstance(end_obj, dict) else None)
    )

    summary = (
        data.get("summary")
        or data.get("title")
        or inner_payload.get("summary")
        or inner_payload.get("title")
        or "(Untitled Meeting)"
    )

    description = data.get("description") or inner_payload.get("description") or ""
    location = data.get("location") or inner_payload.get("location") or ""
    hangout_link = (
        data.get("hangout_link")
        or data.get("hangoutLink")
        or data.get("html_link")
        or data.get("htmlLink")
        or inner_payload.get("hangout_link")
        or inner_payload.get("html_link")
        or ""
    )

    log_id = meta.get("log_id") or payload.get("id") or f"cal_{tenant_id}_{event_id}"

    return CanonicalEvent(
        event_id=log_id,
        event_type=event_type,
        source="google_calendar",
        tenant_id=tenant_id,
        user_id=user_id,
        external_id=event_id,
        raw_ref={
            "event_id": event_id,
            "calendar_id": data.get("calendar_id") or data.get("calendarId", "primary"),
            "connected_account_id": meta.get("connected_account_id") or payload.get("connected_account_id") or payload.get("connectedAccountId"),
        },
        acl=acl,
        timestamp=_parse_ts(data.get("updated_at") or data.get("updated") or start_time),
        metadata={
            "summary": summary,
            "subject": summary,
            "title": summary,
            "name": summary,
            "description": description,
            "location": location,
            "start_time": start_time,
            "end_time": end_time,
            "organizer": organizer or creator,
            "hangout_link": hangout_link,
            "status": status_str,
            "mime_type": "text/markdown",
        },
    )

def _parse_ts(raw) -> datetime:
    return normalize_to_utc(raw)
