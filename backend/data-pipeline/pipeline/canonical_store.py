from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from connectors.events.canonical_event import CanonicalEvent, EventType

@dataclass
class DocumentRecord:
    doc_id: str
    tenant_id: str
    user_id: str
    source: str
    external_id: str
    acl: list[str]
    event_type: str
    status: str  # PENDING_STAGING, STAGED, REJECTED, PROCESSED
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

class CanonicalStore:
    """Canonical & ACL DB Store tracking document lineage and access control snapshots."""

    def __init__(self) -> None:
        self._records: dict[str, DocumentRecord] = {}

    def record_event(self, event: CanonicalEvent, status: str = "PENDING_STAGING") -> DocumentRecord:
        doc_id = f"{event.tenant_id}:{event.source}:{event.external_id}"
        record = DocumentRecord(
            doc_id=doc_id,
            tenant_id=event.tenant_id,
            user_id=event.user_id,
            source=event.source,
            external_id=event.external_id,
            acl=list(event.acl),
            event_type=event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type),
            status=status,
            metadata=event.metadata,
            updated_at=event.timestamp or datetime.now(timezone.utc),
        )
        self._records[doc_id] = record
        print(f"[CanonicalStore] Recorded event lineage for doc_id={doc_id}, status={status}")
        return record

    def get_document(self, doc_id: str) -> DocumentRecord | None:
        return self._records.get(doc_id)

    def update_acl(self, doc_id: str, new_acl: list[str]) -> bool:
        record = self._records.get(doc_id)
        if not record:
            return False
        record.acl = new_acl
        record.updated_at = datetime.now(timezone.utc)
        print(f"[CanonicalStore] Updated ACL snapshot for doc_id={doc_id}: {new_acl}")
        return True

    def mark_status(self, doc_id: str, status: str) -> bool:
        record = self._records.get(doc_id)
        if not record:
            return False
        record.status = status
        record.updated_at = datetime.now(timezone.utc)
        return True
