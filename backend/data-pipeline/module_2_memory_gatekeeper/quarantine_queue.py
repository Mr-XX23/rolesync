from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from module_1_document_processing.parsing.parsed_document import ParsedDocument

@dataclass
class QuarantinedRecord:
    doc_id: str
    tenant_id: str
    reason: str
    document: ParsedDocument
    quarantined_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

class QuarantineQueue:
    """Quarantine queue for low confidence/boundary items requiring review or replay."""

    def __init__(self) -> None:
        self._queue: dict[str, QuarantinedRecord] = {}

    def quarantine(self, document: ParsedDocument, reason: str) -> QuarantinedRecord:
        record = QuarantinedRecord(
            doc_id=document.doc_id,
            tenant_id=document.tenant_id,
            reason=reason,
            document=document,
        )
        self._queue[document.doc_id] = record
        print(f"[QuarantineQueue] Quarantined doc_id={document.doc_id}: {reason}")
        return record

    def release_for_replay(self, doc_id: str) -> ParsedDocument | None:
        record = self._queue.pop(doc_id, None)
        if record:
            print(f"[QuarantineQueue] Released doc_id={doc_id} for replay.")
            return record.document
        return None
