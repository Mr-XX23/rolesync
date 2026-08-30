from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

@dataclass
class DLQRecord:
    doc_id: str
    tenant_id: str
    reason: str
    failed_chunks: list[Any] = field(default_factory=list)
    failed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

class DeadLetterQueue:
    """Dead Letter Queue capturing failed ingestion batches for review and manual replay."""

    def __init__(self) -> None:
        self._queue: list[DLQRecord] = []

    def push_failure(self, doc_id: str, tenant_id: str, reason: str, failed_chunks: list[Any] | None = None) -> DLQRecord:
        record = DLQRecord(doc_id=doc_id, tenant_id=tenant_id, reason=reason, failed_chunks=failed_chunks or [])
        self._queue.append(record)
        print(f"[DeadLetterQueue] Pushed failed batch to DLQ for doc_id={doc_id}: {reason}")
        return record

    def list_failures(self) -> list[DLQRecord]:
        return list(self._queue)
