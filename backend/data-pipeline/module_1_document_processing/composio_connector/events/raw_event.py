from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

@dataclass
class RawEvent:
    raw_id: str
    source: str
    tenant_id: str
    payload: dict[str, Any]
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
