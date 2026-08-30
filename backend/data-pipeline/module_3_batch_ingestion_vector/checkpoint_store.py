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
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

class CheckpointStore:
    """Checkpoint Store tracking batch ingestion progress and state transitions."""

    def __init__(self) -> None:
        self._checkpoints: dict[str, CheckpointRecord] = {}

    def create_checkpoint(self, batch_id: str, doc_id: str, tenant_id: str, chunks_count: int) -> CheckpointRecord:
        record = CheckpointRecord(batch_id=batch_id, doc_id=doc_id, tenant_id=tenant_id, status="PENDING", chunks_count=chunks_count)
        self._checkpoints[batch_id] = record
        return record

    def update_status(self, batch_id: str, status: str) -> None:
        chk = self._checkpoints.get(batch_id)
        if chk:
            chk.status = status
            chk.updated_at = datetime.now(timezone.utc)
            print(f"[CheckpointStore] Updated batch_id={batch_id} status={status}")

    def get_checkpoint(self, batch_id: str) -> CheckpointRecord | None:
        return self._checkpoints.get(batch_id)
