from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from parsing.parsed_document import ParsedDocument

@dataclass
class RejectedRecord:
    doc_id: str
    tenant_id: str
    reason: str
    document: ParsedDocument
    rejected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

class RejectedStore:
    """Store for confident filter-outs with TTL and expiry support."""

    def __init__(self) -> None:
        self._store: dict[str, RejectedRecord] = {}

    def store_rejection(self, document: ParsedDocument, reason: str) -> RejectedRecord:
        record = RejectedRecord(
            doc_id=document.doc_id,
            tenant_id=document.tenant_id,
            reason=reason,
            document=document,
        )
        self._store[document.doc_id] = record
        print(f"[RejectedStore] Stored rejected document doc_id={document.doc_id}: {reason}")
        return record

    def get_rejection(self, doc_id: str) -> RejectedRecord | None:
        return self._store.get(doc_id)
