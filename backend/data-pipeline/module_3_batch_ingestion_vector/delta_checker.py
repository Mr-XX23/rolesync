"""Delta hash checking - skips re-embedding chunks whose content has not changed.

The hash fingerprints live in Postgres (rag.chunk_hashes) so de-duplication works
across uploads and process restarts. Previously these were held in a dictionary
that was recreated per upload, which meant the delta check never actually fired.
Falls back to in-memory when Postgres is unavailable.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from module_3_batch_ingestion_vector.chunker import TextNode

try:
    from sqlalchemy import delete, select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from rag.database import session_scope
    from rag.models import ChunkHash
    from rag.state import persistence_available

    _RAG_AVAILABLE = True
except Exception:  # pragma: no cover - sqlalchemy / rag package unavailable
    _RAG_AVAILABLE = False


class VersionedHashDB:
    """Versioned hash database maintaining chunk fingerprints per doc_id."""

    def __init__(self, use_db: Optional[bool] = None) -> None:
        self._db_mem: dict[str, dict[str, str]] = {}  # doc_id -> {chunk_id: chunk_hash}
        self._db_override: Optional[bool] = None if use_db is None else (bool(use_db) and _RAG_AVAILABLE)

    @property
    def _db(self) -> bool:
        """Resolved lazily so import-time construction does not freeze the decision."""
        if self._db_override is not None:
            return self._db_override
        return _RAG_AVAILABLE and persistence_available()

    def get_chunk_hash(self, doc_id: str, chunk_id: str) -> str | None:
        if self._db:
            try:
                with session_scope() as session:
                    value = session.execute(
                        select(ChunkHash.chunk_hash).where(
                            ChunkHash.doc_id == doc_id, ChunkHash.chunk_id == chunk_id
                        )
                    ).scalar_one_or_none()
                    if value is not None:
                        return value
            except Exception as err:
                print(f"[VersionedHashDB] Postgres read failed for {doc_id}/{chunk_id}: {err}")
        return self._db_mem.get(doc_id, {}).get(chunk_id)

    def get_hashes_for_doc(self, doc_id: str) -> dict[str, str]:
        """All known chunk hashes for a document in a single round trip."""
        if self._db:
            try:
                with session_scope() as session:
                    rows = session.execute(
                        select(ChunkHash.chunk_id, ChunkHash.chunk_hash).where(ChunkHash.doc_id == doc_id)
                    ).all()
                    if rows:
                        return {chunk_id: chunk_hash for chunk_id, chunk_hash in rows}
            except Exception as err:
                print(f"[VersionedHashDB] Postgres bulk read failed for {doc_id}: {err}")
        return dict(self._db_mem.get(doc_id, {}))

    def set_chunk_hash(self, doc_id: str, chunk_id: str, chunk_hash: str) -> None:
        self.set_many([(doc_id, chunk_id, chunk_hash)])

    def set_many(self, entries: list[tuple[str, str, str]]) -> None:
        """Bulk upsert of (doc_id, chunk_id, chunk_hash) fingerprints."""
        if not entries:
            return

        if self._db:
            try:
                now = datetime.now(timezone.utc)
                rows = [
                    {"doc_id": doc_id, "chunk_id": chunk_id, "chunk_hash": chunk_hash, "updated_at": now}
                    for doc_id, chunk_id, chunk_hash in entries
                ]
                with session_scope() as session:
                    stmt = pg_insert(ChunkHash).values(rows)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["doc_id", "chunk_id"],
                        set_={"chunk_hash": stmt.excluded.chunk_hash, "updated_at": now},
                    )
                    session.execute(stmt)
                return
            except Exception as err:
                print(f"[VersionedHashDB] Postgres bulk write failed, using in-memory: {err}")

        for doc_id, chunk_id, chunk_hash in entries:
            self._db_mem.setdefault(doc_id, {})[chunk_id] = chunk_hash

    def clear_document_hashes(self, doc_id: str) -> None:
        if self._db:
            try:
                with session_scope() as session:
                    session.execute(delete(ChunkHash).where(ChunkHash.doc_id == doc_id))
            except Exception as err:
                print(f"[VersionedHashDB] Postgres clear failed for {doc_id}: {err}")
        self._db_mem.pop(doc_id, None)


class DeltaChecker:
    """Prevents redundant re-indexing of unmodified document chunks."""

    def __init__(self, hash_db: VersionedHashDB | None = None) -> None:
        self.hash_db = hash_db or VersionedHashDB()

    def filter_changed_chunks(self, nodes: list[TextNode]) -> tuple[list[TextNode], list[TextNode]]:
        new_or_modified: list[TextNode] = []
        unchanged: list[TextNode] = []

        # One lookup per document rather than one per chunk.
        known: dict[str, dict[str, str]] = {}
        for node in nodes:
            if node.doc_id not in known:
                known[node.doc_id] = self.hash_db.get_hashes_for_doc(node.doc_id)

        for node in nodes:
            existing_hash = known.get(node.doc_id, {}).get(node.chunk_id)
            if existing_hash != node.chunk_hash:
                new_or_modified.append(node)
            else:
                unchanged.append(node)

        print(
            f"[DeltaChecker] Evaluated {len(nodes)} chunks -> "
            f"New/Modified: {len(new_or_modified)}, Unchanged Skipped: {len(unchanged)}"
        )
        return new_or_modified, unchanged

    def commit_chunk_hashes(self, nodes: list[TextNode]) -> None:
        self.hash_db.set_many([(node.doc_id, node.chunk_id, node.chunk_hash) for node in nodes])
