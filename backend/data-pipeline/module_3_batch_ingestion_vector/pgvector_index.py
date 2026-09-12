"""HNSW-backed similarity search over chunk embeddings (pgvector).

Replaces the brute-force Python cosine scan: search now runs as an approximate
nearest-neighbour query against a real HNSW index, with tenant and ACL applied
as SQL filters rather than by loading every row into the process.

Deliberately uses raw SQL and vector literals rather than the `pgvector` Python
package, so no new dependency (and no image rebuild) is required.

Falls back silently when pgvector is unavailable; callers keep their existing
brute-force path.
"""
from __future__ import annotations

import json
from typing import Any, Optional

try:
    from sqlalchemy import bindparam, text

    from rag.database import session_scope
    from rag.state import vector_index_available

    _RAG_AVAILABLE = True
except Exception:  # pragma: no cover - sqlalchemy / rag package unavailable
    _RAG_AVAILABLE = False

TABLE = "rag.vector_chunks"

_UPSERT_SQL = f"""
INSERT INTO {TABLE} (
    vector_id, doc_id, doc_ref_id, tenant_id, user_id, source, external_id,
    text, acl, chunk_index, total_chunks, prev_chunk_id, next_chunk_id, meta,
    embedding, updated_at
) VALUES (
    :vector_id, :doc_id, :doc_ref_id, :tenant_id, :user_id, :source, :external_id,
    :text, CAST(:acl AS jsonb), :chunk_index, :total_chunks, :prev_chunk_id,
    :next_chunk_id, CAST(:meta AS jsonb), CAST(:embedding AS vector), now()
)
ON CONFLICT (vector_id) DO UPDATE SET
    doc_id = EXCLUDED.doc_id,
    doc_ref_id = EXCLUDED.doc_ref_id,
    tenant_id = EXCLUDED.tenant_id,
    user_id = EXCLUDED.user_id,
    source = EXCLUDED.source,
    external_id = EXCLUDED.external_id,
    text = EXCLUDED.text,
    acl = EXCLUDED.acl,
    chunk_index = EXCLUDED.chunk_index,
    total_chunks = EXCLUDED.total_chunks,
    prev_chunk_id = EXCLUDED.prev_chunk_id,
    next_chunk_id = EXCLUDED.next_chunk_id,
    meta = EXCLUDED.meta,
    embedding = EXCLUDED.embedding,
    updated_at = now();
"""

# `<=>` is cosine distance; the ORDER BY is what lets the HNSW index serve the query.
_SEARCH_SQL = f"""
SELECT vector_id, doc_id, doc_ref_id, tenant_id, user_id, source, external_id,
       text, acl, chunk_index, total_chunks, prev_chunk_id, next_chunk_id, meta,
       1 - (embedding <=> CAST(:query AS vector)) AS score
FROM {TABLE}
WHERE tenant_id = :tenant_id
  AND embedding IS NOT NULL
  -- Never serve pseudo-embeddings as search results.
  AND (meta->>'embedding_fallback') IS DISTINCT FROM 'true'
  AND EXISTS (
        SELECT 1 FROM jsonb_array_elements_text(acl) AS entry
        WHERE entry IN :acl_list
  )
ORDER BY embedding <=> CAST(:query AS vector)
LIMIT :limit
"""


def to_vector_literal(values: list[float]) -> str:
    """pgvector accepts a bracketed literal, e.g. '[0.1,0.2]'."""
    return "[" + ",".join(f"{float(v):.8g}" for v in values) + "]"


class PgVectorIndex:
    """Thin data-access layer over rag.vector_chunks."""

    def available(self) -> bool:
        return _RAG_AVAILABLE and vector_index_available()

    # ---- writes ----------------------------------------------------------
    def upsert(self, records: list[Any]) -> int:
        """Upsert VectorRecord-shaped objects. Returns rows written."""
        if not self.available() or not records:
            return 0

        rows = []
        for rec in records:
            vector = getattr(rec, "vector", None) or []
            if not vector:
                continue
            rows.append(
                {
                    "vector_id": rec.vector_id,
                    "doc_id": rec.doc_id,
                    "doc_ref_id": getattr(rec, "doc_ref_id", "") or "",
                    "tenant_id": rec.tenant_id,
                    "user_id": getattr(rec, "user_id", "") or "",
                    "source": (getattr(rec, "source", "") or "").lower(),
                    "external_id": getattr(rec, "external_id", "") or "",
                    "text": getattr(rec, "text", "") or "",
                    "acl": json.dumps(list(getattr(rec, "acl", []) or [])),
                    "chunk_index": int(getattr(rec, "chunk_index", 0) or 0),
                    "total_chunks": int(getattr(rec, "total_chunks", 0) or 0),
                    "prev_chunk_id": getattr(rec, "prev_chunk_id", None),
                    "next_chunk_id": getattr(rec, "next_chunk_id", None),
                    "meta": json.dumps(getattr(rec, "metadata", {}) or {}, default=str),
                    "embedding": to_vector_literal(vector),
                }
            )

        if not rows:
            return 0

        try:
            with session_scope() as session:
                session.execute(text(_UPSERT_SQL), rows)
            return len(rows)
        except Exception as err:
            print(f"[PgVectorIndex] Upsert failed: {err}")
            return 0

    def delete_by_doc_id(self, doc_id: str) -> int:
        return self._delete("doc_id = :doc_id OR doc_ref_id = :doc_id", {"doc_id": doc_id})

    def delete_by_tenant_source_user(self, tenant_id: str, source: str, user_id: str = "") -> int:
        clause = "tenant_id = :tenant_id AND source = :source"
        params: dict[str, Any] = {"tenant_id": tenant_id, "source": (source or "").lower()}
        if user_id:
            clause += " AND user_id = :user_id"
            params["user_id"] = user_id
        return self._delete(clause, params)

    def _delete(self, where_clause: str, params: dict[str, Any]) -> int:
        if not self.available():
            return 0
        try:
            with session_scope() as session:
                result = session.execute(text(f"DELETE FROM {TABLE} WHERE {where_clause}"), params)
                return int(result.rowcount or 0)
        except Exception as err:
            print(f"[PgVectorIndex] Delete failed: {err}")
            return 0

    def update_acl_for_doc_id(self, doc_id: str, new_acl: list[str]) -> int:
        if not self.available():
            return 0
        try:
            with session_scope() as session:
                result = session.execute(
                    text(f"UPDATE {TABLE} SET acl = CAST(:acl AS jsonb), updated_at = now() WHERE doc_id = :doc_id"),
                    {"acl": json.dumps(list(new_acl or [])), "doc_id": doc_id},
                )
                return int(result.rowcount or 0)
        except Exception as err:
            print(f"[PgVectorIndex] ACL update failed: {err}")
            return 0

    # ---- reads -----------------------------------------------------------
    def count(self, tenant_id: str, source: str = "", user_id: str = "") -> int:
        if not self.available():
            return 0
        clause = "tenant_id = :tenant_id"
        params: dict[str, Any] = {"tenant_id": tenant_id}
        if source:
            clause += " AND source = :source"
            params["source"] = source.lower()
        if user_id:
            clause += " AND user_id = :user_id"
            params["user_id"] = user_id
        try:
            with session_scope() as session:
                return int(session.execute(text(f"SELECT count(*) FROM {TABLE} WHERE {clause}"), params).scalar() or 0)
        except Exception as err:
            print(f"[PgVectorIndex] Count failed: {err}")
            return 0

    def list_chunks(self, doc_id: str) -> Optional[list[dict[str, Any]]]:
        """All chunks for a document, ordered. None means the index is unusable."""
        if not self.available() or not doc_id:
            return None
        try:
            with session_scope() as session:
                rows = session.execute(
                    text(
                        f"""
                        SELECT vector_id, doc_id, doc_ref_id, external_id, text, meta,
                               chunk_index, total_chunks, prev_chunk_id, next_chunk_id,
                               vector_dims(embedding) AS dimension, updated_at
                        FROM {TABLE}
                        WHERE doc_id = :doc_id OR doc_ref_id = :doc_id
                        ORDER BY chunk_index
                        """
                    ),
                    {"doc_id": doc_id},
                ).mappings().all()
            return [dict(row) for row in rows]
        except Exception as err:
            print(f"[PgVectorIndex] Chunk listing failed for {doc_id}: {err}")
            return None

    def search(
        self,
        query_vector: list[float],
        tenant_id: str,
        user_acl: list[str],
        limit: int = 5,
        min_score: float = 0.0,
    ) -> Optional[list[dict[str, Any]]]:
        """Top-k by cosine similarity. None means "index unusable, use fallback"."""
        if not self.available() or not query_vector:
            return None
        # An empty ACL grants nothing; returning [] avoids generating invalid SQL.
        if not user_acl:
            return []

        statement = text(_SEARCH_SQL).bindparams(bindparam("acl_list", expanding=True))
        try:
            with session_scope() as session:
                rows = session.execute(
                    statement,
                    {
                        "query": to_vector_literal(query_vector),
                        "tenant_id": tenant_id,
                        "acl_list": list(user_acl),
                        "limit": int(limit),
                    },
                ).mappings().all()
            return [dict(row) for row in rows if float(row["score"] or 0) >= min_score]
        except Exception as err:
            print(f"[PgVectorIndex] Search failed, falling back: {err}")
            return None


pgvector_index = PgVectorIndex()
