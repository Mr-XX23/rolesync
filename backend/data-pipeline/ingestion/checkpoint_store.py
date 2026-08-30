from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

@dataclass
class CheckpointRecord:
    batch_id: str
    doc_id: str
    tenant_id: str
    status: str  # PENDING, PROCESSING, DONE, FAILED
    chunks_count: int = 0
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

class CheckpointStore:
    """Store for tracking batch state transitions: PENDING -> PROCESSING -> DONE -> FAILED."""

    def __init__(self) -> None:
        self._checkpoints: dict[str, CheckpointRecord] = {}

    def create_checkpoint(self, batch_id: str, doc_id: str, tenant_id: str, chunks_count: int = 0) -> CheckpointRecord:
        record = CheckpointRecord(
            batch_id=batch_id,
            doc_id=doc_id,
            tenant_id=tenant_id,
            status="PENDING",
            chunks_count=chunks_count,
        )
        self._checkpoints[batch_id] = record
        return record

    def update_status(self, batch_id: str, status: str) -> None:
        record = self._checkpoints.get(batch_id)
        if record:
            record.status = status
            record.updated_at = datetime.now(timezone.utc)
            print(f"[CheckpointStore] Updated batch_id={batch_id} status={status}")

    def get_checkpoint(self, batch_id: str) -> CheckpointRecord | None:
        return self._checkpoints.get(batch_id)
