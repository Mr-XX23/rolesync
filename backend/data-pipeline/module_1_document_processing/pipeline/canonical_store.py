"""Canonical Store - the pipeline's source of truth for a document lifecycle.

Backed by Postgres (rag.documents + rag.document_events) so status, the ACL
snapshot and lineage survive a restart. Falls back to in-memory storage when
Postgres is unavailable (tests, local dev, outage) so ingestion never breaks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent

try:
    from sqlalchemy import delete, select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from rag.database import session_scope
    from rag.models import DocumentEvent, RagDocument
    from rag.state import persistence_available

    _RAG_AVAILABLE = True
except Exception:  # pragma: no cover - sqlalchemy / rag package unavailable
    _RAG_AVAILABLE = False


@dataclass
class StagedDocument:
    doc_id: str
    tenant_id: str
    user_id: str
    source: str
    external_id: str
    status: str  # STAGED, PARSED_SUCCESS, PARSED_FAILED, GATEKEEPER_*, VECTOR_STORE_INDEXED, DELETED
    event_history: list[CanonicalEvent] = field(default_factory=list)
    acl: list[str] = field(default_factory=list)
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class CanonicalStore:
    """Tracks raw lineage, ACL snapshots and document lifecycle status."""

    def __init__(self, use_db: Optional[bool] = None) -> None:
        self._store: dict[str, StagedDocument] = {}
        self._db_override: Optional[bool] = None if use_db is None else (bool(use_db) and _RAG_AVAILABLE)

    @property
    def _db(self) -> bool:
        """Resolved lazily: stores are constructed at import time, before the
        application lifespan decides whether Postgres persistence is available."""
        if self._db_override is not None:
            return self._db_override
        return _RAG_AVAILABLE and persistence_available()

    # ---- helpers ---------------------------------------------------------
    @staticmethod
    def _doc_id(event: CanonicalEvent) -> str:
        return f"{event.tenant_id}:{event.source}:{event.external_id}"

    @staticmethod
    def _event_type_str(event: CanonicalEvent) -> str:
        raw = getattr(event, "event_type", "")
        return str(getattr(raw, "value", raw) or "")

    @staticmethod
    def _json_safe(value, _depth: int = 0):
        """Coerce an event payload into something JSONB accepts.

        Connector metadata legitimately carries raw bytes (attachment payloads).
        Passing those straight to a JSONB column raises
        "Object of type bytes is not JSON serializable", which previously failed
        the whole lineage write and silently dropped the document to in-memory.
        """
        if _depth > 6:
            return "<nested>"
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, (bytes, bytearray, memoryview)):
            return f"<bytes len={len(bytes(value))}>"
        if isinstance(value, dict):
            return {str(k): CanonicalStore._json_safe(v, _depth + 1) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [CanonicalStore._json_safe(v, _depth + 1) for v in value]
        return str(value)

    @staticmethod
    def _row_to_staged(row) -> StagedDocument:
        return StagedDocument(
            doc_id=row.doc_id,
            tenant_id=row.tenant_id,
            user_id=row.user_id,
            source=row.source,
            external_id=row.external_id,
            status=row.status,
            acl=list(row.acl or []),
            updated_at=row.updated_at or datetime.now(timezone.utc),
        )

    # ---- public API ------------------------------------------------------
    def record_event(self, event: CanonicalEvent, status: str = "STAGED") -> StagedDocument:
        doc_id = self._doc_id(event)
        now = datetime.now(timezone.utc)
        acl = list(event.acl or [])

        if self._db:
            try:
                with session_scope() as session:
                    stmt = pg_insert(RagDocument).values(
                        doc_id=doc_id,
                        tenant_id=event.tenant_id or "",
                        user_id=event.user_id or "",
                        source=event.source or "",
                        external_id=event.external_id or "",
                        status=status,
                        acl=acl,
                        event_count=1,
                        created_at=now,
                        updated_at=now,
                    )
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["doc_id"],
                        set_={
                            "status": status,
                            "acl": acl,
                            "user_id": event.user_id or "",
                            "event_count": RagDocument.event_count + 1,
                            "updated_at": now,
                        },
                    )
                    session.execute(stmt)
                    session.execute(
                        pg_insert(DocumentEvent).values(
                            doc_id=doc_id,
                            event_id=getattr(event, "event_id", "") or "",
                            event_type=self._event_type_str(event),
                            status=status,
                            payload={"metadata": self._json_safe(dict(getattr(event, "metadata", {}) or {}))},
                            created_at=now,
                        )
                    )
                print(f"[CanonicalStore] Recorded event lineage for doc_id={doc_id}, status={status}")
                return StagedDocument(
                    doc_id=doc_id,
                    tenant_id=event.tenant_id or "",
                    user_id=event.user_id or "",
                    source=event.source or "",
                    external_id=event.external_id or "",
                    status=status,
                    acl=acl,
                    updated_at=now,
                )
            except Exception as err:
                print(f"[CanonicalStore] Postgres write failed for {doc_id}, using in-memory: {err}")

        staged = self._store.get(doc_id)
        if staged is None:
            staged = StagedDocument(
                doc_id=doc_id,
                tenant_id=event.tenant_id or "",
                user_id=event.user_id or "",
                source=event.source or "",
                external_id=event.external_id or "",
                status=status,
                acl=acl,
            )
            self._store[doc_id] = staged
        else:
            staged.status = status
            staged.acl = acl
            staged.updated_at = now

        staged.event_history.append(event)
        print(f"[CanonicalStore] Recorded event lineage for doc_id={doc_id}, status={status}")
        return staged

    def get_document(self, doc_id: str) -> StagedDocument | None:
        if self._db:
            try:
                with session_scope() as session:
                    row = session.execute(
                        select(RagDocument).where(RagDocument.doc_id == doc_id)
                    ).scalar_one_or_none()
                    if row is not None:
                        return self._row_to_staged(row)
            except Exception as err:
                print(f"[CanonicalStore] Postgres read failed for {doc_id}: {err}")
        return self._store.get(doc_id)

    def update_acl(self, doc_id: str, new_acl: list[str]) -> bool:
        acl = list(new_acl or [])
        now = datetime.now(timezone.utc)

        if self._db:
            try:
                with session_scope() as session:
                    row = session.execute(
                        select(RagDocument).where(RagDocument.doc_id == doc_id)
                    ).scalar_one_or_none()
                    if row is not None:
                        row.acl = acl
                        row.updated_at = now
                        print(f"[CanonicalStore] Updated ACL snapshot for doc_id={doc_id}: {acl}")
                        return True
            except Exception as err:
                print(f"[CanonicalStore] Postgres ACL update failed for {doc_id}: {err}")

        staged = self._store.get(doc_id)
        if staged:
            staged.acl = acl
            staged.updated_at = now
            print(f"[CanonicalStore] Updated ACL snapshot for doc_id={doc_id}: {acl}")
            return True
        return False

    def mark_status(self, doc_id: str, status: str) -> bool:
        """Set lifecycle status directly (used by the deletion cascade)."""
        now = datetime.now(timezone.utc)
        if self._db:
            try:
                with session_scope() as session:
                    row = session.execute(
                        select(RagDocument).where(RagDocument.doc_id == doc_id)
                    ).scalar_one_or_none()
                    if row is not None:
                        row.status = status
                        row.updated_at = now
                        return True
            except Exception as err:
                print(f"[CanonicalStore] Postgres status update failed for {doc_id}: {err}")

        staged = self._store.get(doc_id)
        if staged:
            staged.status = status
            staged.updated_at = now
            return True
        return False

    def list_documents(
        self,
        tenant_id: str,
        source: str = "",
        exclude_statuses: tuple[str, ...] = ("DELETED",),
    ) -> list[StagedDocument]:
        """Documents for a tenant (optionally one source). Used by the reconciliation sweeper."""
        if self._db:
            try:
                with session_scope() as session:
                    stmt = select(RagDocument).where(RagDocument.tenant_id == tenant_id)
                    if source:
                        stmt = stmt.where(RagDocument.source == source)
                    if exclude_statuses:
                        stmt = stmt.where(RagDocument.status.notin_(list(exclude_statuses)))
                    rows = session.execute(stmt).scalars().all()
                    return [self._row_to_staged(row) for row in rows]
            except Exception as err:
                print(f"[CanonicalStore] Postgres list failed for tenant={tenant_id}: {err}")

        return [
            doc
            for doc in self._store.values()
            if doc.tenant_id == tenant_id
            and (not source or doc.source == source)
            and doc.status not in (exclude_statuses or ())
        ]

    def purge_by_tenant_source_user(self, tenant_id: str, source: str, user_id: str = "") -> int:
        count = 0
        if self._db:
            try:
                with session_scope() as session:
                    stmt = delete(RagDocument).where(
                        RagDocument.tenant_id == tenant_id,
                        RagDocument.source == source.lower(),
                    )
                    if user_id:
                        stmt = stmt.where(RagDocument.user_id == user_id)
                    count = int(session.execute(stmt).rowcount or 0)
            except Exception as err:
                print(f"[CanonicalStore] Postgres purge failed for tenant={tenant_id}: {err}")

        to_delete = [
            doc_id
            for doc_id, doc in self._store.items()
            if doc.tenant_id == tenant_id
            and doc.source.lower() == source.lower()
            and (not user_id or doc.user_id == user_id)
        ]
        for doc_id in to_delete:
            self._store.pop(doc_id, None)

        count = max(count, len(to_delete))
        print(f"[CanonicalStore] Purged {count} staged docs for tenant={tenant_id}, source={source}, user={user_id}.")
        return count
