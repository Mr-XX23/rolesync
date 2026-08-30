from datetime import datetime, timezone
from connectors.events.canonical_event import CanonicalEvent, EventType

def normalize_calendar(payload: dict, tenant_id: str) -> CanonicalEvent:
    meta = payload.get("metadata", {})
    data = payload.get("data", {})

    slug = meta.get("trigger_slug", "")
    event_type = EventType.UPDATE
    if "CREATED" in slug or "ADD" in slug:
        event_type = EventType.CREATE
    elif "DELETED" in slug or "CANCELLED" in slug:
        event_type = EventType.DELETE

    attendees = data.get("attendees") or []
    acl = [a.get("email") for a in attendees if isinstance(a, dict) and a.get("email")]
    creator = data.get("creator", {}).get("email") if isinstance(data.get("creator"), dict) else None
    if creator and creator not in acl:
        acl.append(creator)
    if not acl:
        acl = [meta.get("user_id", "owner")]

    start_time = data.get("start", {}).get("dateTime") or data.get("start", {}).get("date")
    end_time = data.get("end", {}).get("dateTime") or data.get("end", {}).get("date")

    return CanonicalEvent(
        event_id=meta.get("log_id") or data.get("id", ""),
        event_type=event_type,
        source="google_calendar",
        tenant_id=tenant_id,
        user_id=meta.get("user_id", ""),
        external_id=data.get("id") or data.get("eventId", ""),
        raw_ref={
            "event_id": data.get("id") or data.get("eventId"),
            "calendar_id": data.get("calendarId", "primary"),
            "connected_account_id": meta.get("connected_account_id"),
        },
        acl=acl,
        timestamp=_parse_ts(data.get("updated") or start_time),
        metadata={
            "summary": data.get("summary") or data.get("title"),
            "description": data.get("description"),
            "location": data.get("location"),
            "start_time": start_time,
            "end_time": end_time,
            "organizer": data.get("organizer", {}).get("email") if isinstance(data.get("organizer"), dict) else None,
            "hangout_link": data.get("hangoutLink") or data.get("htmlLink"),
        },
    )

def _parse_ts(raw) -> datetime:
    if not raw:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
