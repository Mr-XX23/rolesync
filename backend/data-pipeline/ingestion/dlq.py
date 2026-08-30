from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from ingestion.chunker import ChunkNode

@dataclass
class DLQRecord:
    dlq_id: str
    doc_id: str
    tenant_id: str
    reason: str
    failed_chunks: list[ChunkNode]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

class DeadLetterQueue:
    """Dead Letter Queue capturing exhausted pipeline retry failures."""

    def __init__(self) -> None:
        self._dlq: dict[str, DLQRecord] = {}

    def push_failure(self, doc_id: str, tenant_id: str, reason: str, failed_chunks: list[ChunkNode]) -> DLQRecord:
        dlq_id = f"dlq_{doc_id}_{len(self._dlq) + 1}"
        record = DLQRecord(
            dlq_id=dlq_id,
            doc_id=doc_id,
            tenant_id=tenant_id,
            reason=reason,
            failed_chunks=failed_chunks,
        )
        self._dlq[dlq_id] = record
        print(f"[DeadLetterQueue] Pushed failure to DLQ dlq_id={dlq_id} for doc_id={doc_id}: {reason}")
        return record

    def get_failures() -> list[DLQRecord]:
        return list(self._dlq.values())
