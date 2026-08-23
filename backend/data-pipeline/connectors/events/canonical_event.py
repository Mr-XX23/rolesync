from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
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
    source: str              
    tenant_id: str
    user_id: str
    external_id: str         
    raw_ref: dict[str, Any]  
    acl: list[str]         
    timestamp: datetime
    metadata: dict[str, Any] = field(default_factory=dict)