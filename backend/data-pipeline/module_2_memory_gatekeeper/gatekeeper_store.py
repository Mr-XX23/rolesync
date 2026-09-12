"""Durable storage for gatekeeper decisions and held documents.

Replaces three in-memory dictionaries (audit log, rejected store, quarantine
queue). Two problems with those: the audit trail - a compliance record of what
was kept out of the knowledge base - vanished on restart, and the rejected and
quarantined stores retained the ENTIRE ParsedDocument forever, so a few large
rejected files leaked megabytes with no eviction.

Here decisions go to rag.gatekeeper_audit, held documents to rag.gatekeeper_holds
with a preview plus a real `expires_at`, and expired holds are purged on write.
Falls back to in-memory when Postgres is unavailable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from module_1_document_processing.parsing.parsed_document import ParsedDocument

try:
    from sqlalchemy import delete, or_, select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from rag.database import session_scope
    from rag.models import GatekeeperAudit, GatekeeperHold
    from rag.state import persistence_available

    _RAG_AVAILABLE = True
except Exception:  # pragma: no cover - sqlalchemy / rag package unavailable
    _RAG_AVAILABLE = False

PREVIEW_CHARS = 500


def _matches_id(stored: str, wanted: str) -> bool:
    """Ids are stored canonically ({tenant}:{source}:{external_id}) but callers
    hold the short vault id, so accept either form."""
    return stored == wanted or (":" not in wanted and stored.endswith(f":{wanted}"))
KIND_REJECTED = "REJECTED"
KIND_QUARANTINED = "QUARANTINED"


@dataclass
class HoldRecord:
    doc_id: str
    kind: str
    tenant_id: str
    reason: str
    preview: str
    char_count: int = 0
    category: str = ""
    source: str = ""
    user_id: str = ""
    semantic_score: Optional[float] = None
    status: str = "HELD"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None


class GatekeeperStore:
    def __init__(self, use_db: Optional[bool] = None) -> None:
        self._audit: list[dict[str, Any]] = []
        self._holds: dict[str, HoldRecord] = {}
        self._db_override: Optional[bool] = None if use_db is None else (bool(use_db) and _RAG_AVAILABLE)

    @property
    def _db(self) -> bool:
        if self._db_override is not None:
            return self._db_override
        return _RAG_AVAILABLE and persistence_available()

    # ---- audit -----------------------------------------------------------
    def record_decision(
        self,
        doc_id: str,
        tenant_id: str,
        user_id: str,
        source: str,
        category: str,
        decision: str,
        reason: str,
        entropy: float = 0.0,
        unique_ratio: float = 0.0,
        semantic_score: Optional[float] = None,
        semantic_model: str = "",
        semantic_enforced: bool = False,
        policy_version: str = "",
    ) -> bool:
        row = {
            "doc_id": doc_id,
            "tenant_id": tenant_id or "",
            "user_id": user_id or "",
            "source": source or "",
            "category": category or "",
            "decision": decision,
            "reason": (reason or "")[:2000],
            "entropy": float(entropy or 0.0),
            "unique_ratio": float(unique_ratio or 0.0),
            "semantic_score": semantic_score,
            "semantic_model": semantic_model or "",
            "semantic_enforced": bool(semantic_enforced),
            "policy_version": policy_version or "",
        }

        if self._db:
            try:
                with session_scope() as session:
                    session.execute(pg_insert(GatekeeperAudit).values(**row))
                return True
            except Exception as err:
                print(f"[GatekeeperStore] Audit write failed for {doc_id}: {err}")

        self._audit.append({**row, "created_at": datetime.now(timezone.utc)})
        return False

    @staticmethod
    def _id_clause(column, doc_id: str):
        if ":" in doc_id:
            return column == doc_id
        return or_(column == doc_id, column.like(f"%:{doc_id}"))

    def decisions_for_doc(self, doc_id: str, tenant_id: str = "", limit: int = 50) -> list[dict[str, Any]]:
        """Audit trail for a document. `tenant_id` scopes the read so decisions
        cannot be read across workspaces."""
        if self._db:
            try:
                with session_scope() as session:
                    stmt = select(GatekeeperAudit).where(self._id_clause(GatekeeperAudit.doc_id, doc_id))
                    if tenant_id:
                        stmt = stmt.where(GatekeeperAudit.tenant_id == tenant_id)
                    rows = session.execute(
                        stmt.order_by(GatekeeperAudit.created_at.desc()).limit(limit)
                    ).scalars().all()
                    return [self._audit_to_dict(r) for r in rows]
            except Exception as err:
                print(f"[GatekeeperStore] Audit read failed for {doc_id}: {err}")
        return [
            e for e in self._audit
            if _matches_id(e["doc_id"], doc_id) and (not tenant_id or e["tenant_id"] == tenant_id)
        ][:limit]

    @staticmethod
    def _audit_to_dict(row) -> dict[str, Any]:
        return {
            "doc_id": row.doc_id,
            "tenant_id": row.tenant_id,
            "source": row.source,
            "category": row.category,
            "decision": row.decision,
            "reason": row.reason,
            "entropy": row.entropy,
            "unique_ratio": row.unique_ratio,
            "semantic_score": row.semantic_score,
            "semantic_model": row.semantic_model,
            "semantic_enforced": row.semantic_enforced,
            "policy_version": row.policy_version,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    # ---- holds -----------------------------------------------------------
    def hold(
        self,
        kind: str,
        document: ParsedDocument,
        reason: str,
        ttl_days: int,
        category: str = "",
        semantic_score: Optional[float] = None,
    ) -> HoldRecord:
        text = document.text_content or ""
        now = datetime.now(timezone.utc)
        record = HoldRecord(
            doc_id=document.doc_id,
            kind=kind,
            tenant_id=document.tenant_id or "",
            user_id=document.user_id or "",
            source=document.source or "",
            category=category,
            reason=(reason or "")[:2000],
            # A preview, never the whole document: the old stores kept full text
            # in memory with no eviction.
            preview=text[:PREVIEW_CHARS],
            char_count=len(text),
            semantic_score=semantic_score,
            created_at=now,
            expires_at=now + timedelta(days=max(1, ttl_days)) if ttl_days else None,
        )

        if self._db:
            try:
                with session_scope() as session:
                    statement = pg_insert(GatekeeperHold).values(
                        doc_id=record.doc_id,
                        kind=record.kind,
                        tenant_id=record.tenant_id,
                        user_id=record.user_id,
                        source=record.source,
                        category=record.category,
                        reason=record.reason,
                        preview=record.preview,
                        char_count=record.char_count,
                        semantic_score=record.semantic_score,
                        status="HELD",
                        created_at=record.created_at,
                        expires_at=record.expires_at,
                    )
                    session.execute(
                        statement.on_conflict_do_update(
                            index_elements=["doc_id"],
                            set_={
                                "kind": statement.excluded.kind,
                                "reason": statement.excluded.reason,
                                "preview": statement.excluded.preview,
                                "char_count": statement.excluded.char_count,
                                "semantic_score": statement.excluded.semantic_score,
                                "status": "HELD",
                                "expires_at": statement.excluded.expires_at,
                            },
                        )
                    )
                    # Opportunistic TTL enforcement - the expiry the architecture
                    # asked for, which the previous store never implemented.
                    session.execute(
                        delete(GatekeeperHold).where(
                            GatekeeperHold.expires_at.isnot(None),
                            GatekeeperHold.expires_at < now,
                        )
                    )
                return record
            except Exception as err:
                print(f"[GatekeeperStore] Hold write failed for {record.doc_id}: {err}")

        self._holds[record.doc_id] = record
        self._purge_memory()
        return record

    def get_hold(self, doc_id: str, tenant_id: str = "") -> Optional[HoldRecord]:
        if self._db:
            try:
                with session_scope() as session:
                    stmt = select(GatekeeperHold).where(self._id_clause(GatekeeperHold.doc_id, doc_id))
                    if tenant_id:
                        stmt = stmt.where(GatekeeperHold.tenant_id == tenant_id)
                    row = session.execute(stmt.limit(1)).scalars().first()
                    if row is not None:
                        return self._hold_from_row(row)
            except Exception as err:
                print(f"[GatekeeperStore] Hold read failed for {doc_id}: {err}")
        for record in self._holds.values():
            if _matches_id(record.doc_id, doc_id) and (not tenant_id or record.tenant_id == tenant_id):
                return record
        return None

    def list_holds(self, tenant_id: str, kind: str = "", limit: int = 100) -> list[HoldRecord]:
        if self._db:
            try:
                with session_scope() as session:
                    stmt = select(GatekeeperHold).where(
                        GatekeeperHold.tenant_id == tenant_id,
                        GatekeeperHold.status == "HELD",
                    )
                    if kind:
                        stmt = stmt.where(GatekeeperHold.kind == kind.upper())
                    rows = session.execute(
                        stmt.order_by(GatekeeperHold.created_at.desc()).limit(limit)
                    ).scalars().all()
                    return [self._hold_from_row(r) for r in rows]
            except Exception as err:
                print(f"[GatekeeperStore] Hold listing failed for {tenant_id}: {err}")

        self._purge_memory()
        return [
            h for h in self._holds.values()
            if h.tenant_id == tenant_id and h.status == "HELD" and (not kind or h.kind == kind.upper())
        ][:limit]

    def release(self, doc_id: str) -> bool:
        """Mark a held document released for replay (human review outcome)."""
        if self._db:
            try:
                with session_scope() as session:
                    row = session.execute(
                        select(GatekeeperHold).where(GatekeeperHold.doc_id == doc_id)
                    ).scalar_one_or_none()
                    if row is not None:
                        row.status = "RELEASED"
                        return True
            except Exception as err:
                print(f"[GatekeeperStore] Release failed for {doc_id}: {err}")

        record = self._holds.get(doc_id)
        if record:
            record.status = "RELEASED"
            return True
        return False

    def purge_expired(self) -> int:
        if self._db:
            try:
                with session_scope() as session:
                    result = session.execute(
                        delete(GatekeeperHold).where(
                            GatekeeperHold.expires_at.isnot(None),
                            GatekeeperHold.expires_at < datetime.now(timezone.utc),
                        )
                    )
                    return int(result.rowcount or 0)
            except Exception as err:
                print(f"[GatekeeperStore] Purge failed: {err}")
        return self._purge_memory()

    def _purge_memory(self) -> int:
        now = datetime.now(timezone.utc)
        expired = [k for k, v in self._holds.items() if v.expires_at and v.expires_at < now]
        for key in expired:
            self._holds.pop(key, None)
        return len(expired)

    @staticmethod
    def _hold_from_row(row) -> HoldRecord:
        return HoldRecord(
            doc_id=row.doc_id,
            kind=row.kind,
            tenant_id=row.tenant_id,
            user_id=row.user_id,
            source=row.source,
            category=row.category,
            reason=row.reason,
            preview=row.preview,
            char_count=row.char_count,
            semantic_score=row.semantic_score,
            status=row.status,
            created_at=row.created_at,
            expires_at=row.expires_at,
        )


gatekeeper_store = GatekeeperStore()
