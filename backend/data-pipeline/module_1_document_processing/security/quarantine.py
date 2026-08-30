from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent

@dataclass
class QuarantineRecord:
    quarantine_id: str
    tenant_id: str
    reason: str
    event: CanonicalEvent
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

class QuarantineStore:
    """Store for quarantined unsafe or suspicious payload events."""

    def __init__(self) -> None:
        self._records: dict[str, QuarantineRecord] = {}

    def quarantine_event(self, event: CanonicalEvent, reason: str) -> QuarantineRecord:
        qid = f"quarantine_{event.event_id}"
        record = QuarantineRecord(quarantine_id=qid, tenant_id=event.tenant_id, reason=reason, event=event)
        self._records[qid] = record
        print(f"[QuarantineStore] Quarantined payload event_id={event.event_id}: {reason}")
        return record
