"""Checkpoint store tracking batch ingestion progress.

Persisted to Postgres (rag.checkpoints) so an interrupted batch is still visible
after a restart and can be resumed, instead of vanishing with the process.
Falls back to in-memory when Postgres is unavailable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

try:
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from rag.database import session_scope
    from rag.models import Checkpoint
    from rag.state import persistence_available

    _RAG_AVAILABLE = True
except Exception:  # pragma: no cover - sqlalchemy / rag package unavailable
    _RAG_AVAILABLE = False


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
    """Tracks batch ingestion progress and state transitions."""

    def __init__(self, use_db: Optional[bool] = None) -> None:
        self._checkpoints: dict[str, CheckpointRecord] = {}
        self._db_override: Optional[bool] = None if use_db is None else (bool(use_db) and _RAG_AVAILABLE)

    @property
    def _db(self) -> bool:
        """Resolved lazily so import-time construction does not freeze the decision."""
        if self._db_override is not None:
            return self._db_override
        return _RAG_AVAILABLE and persistence_available()

    @staticmethod
    def _row_to_record(row) -> CheckpointRecord:
        return CheckpointRecord(
            batch_id=row.batch_id,
            doc_id=row.doc_id,
            tenant_id=row.tenant_id,
            status=row.status,
            chunks_count=row.chunks_count or 0,
            created_at=row.created_at or datetime.now(timezone.utc),
            updated_at=row.updated_at or datetime.now(timezone.utc),
        )

    def create_checkpoint(self, batch_id: str, doc_id: str, tenant_id: str, chunks_count: int) -> CheckpointRecord:
        now = datetime.now(timezone.utc)
        record = CheckpointRecord(
            batch_id=batch_id,
            doc_id=doc_id,
            tenant_id=tenant_id,
            status="PENDING",
            chunks_count=chunks_count,
            created_at=now,
            updated_at=now,
        )

        if self._db:
            try:
                with session_scope() as session:
                    stmt = pg_insert(Checkpoint).values(
                        batch_id=batch_id,
                        doc_id=doc_id,
                        tenant_id=tenant_id,
                        status="PENDING",
                        chunks_count=chunks_count,
                        created_at=now,
                        updated_at=now,
                    )
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["batch_id"],
                        set_={
                            "doc_id": doc_id,
                            "tenant_id": tenant_id,
                            "status": "PENDING",
                            "chunks_count": chunks_count,
                            "updated_at": now,
                        },
                    )
                    session.execute(stmt)
                return record
            except Exception as err:
                print(f"[CheckpointStore] Postgres create failed for {batch_id}, using in-memory: {err}")

        self._checkpoints[batch_id] = record
        return record

    def update_status(self, batch_id: str, status: str) -> None:
        now = datetime.now(timezone.utc)

        if self._db:
            try:
                with session_scope() as session:
                    row = session.execute(
                        select(Checkpoint).where(Checkpoint.batch_id == batch_id)
                    ).scalar_one_or_none()
                    if row is not None:
                        row.status = status
                        row.updated_at = now
                        print(f"[CheckpointStore] Updated batch_id={batch_id} status={status}")
                        return
            except Exception as err:
                print(f"[CheckpointStore] Postgres status update failed for {batch_id}: {err}")

        chk = self._checkpoints.get(batch_id)
        if chk:
            chk.status = status
            chk.updated_at = now
            print(f"[CheckpointStore] Updated batch_id={batch_id} status={status}")

    def get_checkpoint(self, batch_id: str) -> CheckpointRecord | None:
        if self._db:
            try:
                with session_scope() as session:
                    row = session.execute(
                        select(Checkpoint).where(Checkpoint.batch_id == batch_id)
                    ).scalar_one_or_none()
                    if row is not None:
                        return self._row_to_record(row)
            except Exception as err:
                print(f"[CheckpointStore] Postgres read failed for {batch_id}: {err}")
        return self._checkpoints.get(batch_id)

    def list_by_status(self, status: str, tenant_id: str = "", limit: int = 100) -> list[CheckpointRecord]:
        """Batches in a given state - the basis for resuming work after a restart."""
        if self._db:
            try:
                with session_scope() as session:
                    stmt = select(Checkpoint).where(Checkpoint.status == status)
                    if tenant_id:
                        stmt = stmt.where(Checkpoint.tenant_id == tenant_id)
                    rows = session.execute(stmt.limit(limit)).scalars().all()
                    return [self._row_to_record(row) for row in rows]
            except Exception as err:
                print(f"[CheckpointStore] Postgres list failed for status={status}: {err}")

        return [
            chk
            for chk in self._checkpoints.values()
            if chk.status == status and (not tenant_id or chk.tenant_id == tenant_id)
        ][:limit]
