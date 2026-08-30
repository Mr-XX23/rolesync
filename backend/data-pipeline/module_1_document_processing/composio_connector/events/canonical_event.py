from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

class EventType(str, Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    ACL_CHANGE = "ACL_CHANGE"

@dataclass
class CanonicalEvent:
    event_id: str
    event_type: EventType
    source: str          # e.g., "gmail", "gdrive", "google_calendar", "slack", "notion"
    tenant_id: str
    user_id: str
    external_id: str     # ID in the source system
    raw_ref: dict[str, Any]
    acl: list[str]       # list of authorized emails, user_ids, or channel IDs
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)
