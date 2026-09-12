from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
import os
import math

try:
    import pymongo
except ImportError:
    pymongo = None

try:
    # Optional HNSW index. Mongo remains the chunk record store; pgvector is
    # the similarity index, so nothing the vault UI reads changes.
    from module_3_batch_ingestion_vector.pgvector_index import pgvector_index
except Exception:  # pragma: no cover
    pgvector_index = None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors; 0.0 if either is empty
    or a different length (e.g. a legacy pseudo-vector vs a real embedding)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))

@dataclass
class VectorRecord:
    vector_id: str
    doc_id: str
    tenant_id: str
    user_id: str
    source: str
    external_id: str
    text: str
    vector: list[float]
    acl: list[str]
    chunk_index: int
    doc_ref_id: str = ""
    prev_chunk_id: Optional[str] = None
    next_chunk_id: Optional[str] = None
    total_chunks: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "vector_id": self.vector_id,
            "doc_id": self.doc_id,
            "doc_ref_id": self.doc_ref_id or self.external_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "source": self.source,
            "external_id": self.external_id,
            "text": self.text,
            "vector": self.vector,
            "acl": self.acl,
            "chunk_index": self.chunk_index,
            "total_chunks": self.total_chunks,
            "prev_chunk_id": self.prev_chunk_id,
            "next_chunk_id": self.next_chunk_id,
            "metadata": self.metadata,
            "updated_at": self.updated_at.isoformat() if isinstance(self.updated_at, datetime) else str(self.updated_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VectorRecord":
        updated_at = datetime.now(timezone.utc)
        if data.get("updated_at"):
            try:
                updated_at = datetime.fromisoformat(data["updated_at"])
            except Exception:
                pass
        return cls(
            vector_id=data.get("vector_id", ""),
            doc_id=data.get("doc_id", ""),
            tenant_id=data.get("tenant_id", ""),
            user_id=data.get("user_id", ""),
            source=data.get("source", ""),
            external_id=data.get("external_id", ""),
            text=data.get("text", ""),
            vector=data.get("vector", []),
            acl=data.get("acl", []),
            chunk_index=data.get("chunk_index", 0),
            doc_ref_id=data.get("doc_ref_id", data.get("external_id", "")),
            prev_chunk_id=data.get("prev_chunk_id"),
            next_chunk_id=data.get("next_chunk_id"),
            total_chunks=data.get("total_chunks", 0),
            metadata=data.get("metadata", {}),
            updated_at=updated_at,
        )

class VectorStore:
    """MongoDB Atlas & In-Memory Vector Store executing persistent storage, ACL security pre-filtering, and similarity searches."""

    def __init__(self) -> None:
        self.mongo_uri = os.environ.get("MONGODB_URI", "mongodb://mongodb:27017")
        self.db_name = os.environ.get("MONGODB_DB_NAME", "rolesync_rag")
        self.collection_name = "vector_chunks"
        self._in_memory: dict[str, VectorRecord] = {}

        self._mongo_client = None
        self._collection = None
        if pymongo and self.mongo_uri:
            try:
                self._mongo_client = pymongo.MongoClient(self.mongo_uri, serverSelectionTimeoutMS=500)
                self._mongo_client.admin.command("ping")
                self._collection = self._mongo_client[self.db_name][self.collection_name]
                self._collection.create_index([("tenant_id", pymongo.ASCENDING), ("source", pymongo.ASCENDING), ("user_id", pymongo.ASCENDING)])
                self._collection.create_index([("doc_id", pymongo.ASCENDING)])
                self._collection.create_index([("doc_ref_id", pymongo.ASCENDING)])
                print(f"[VectorStore] Initialized persistent MongoDB collection '{self.collection_name}' at {self.mongo_uri}/{self.db_name}")
            except Exception as err:
                print(f"[VectorStore] MongoDB offline / local mode ({err})")
                self._collection = None

    @staticmethod
    def _record_from_row(row: dict[str, Any]) -> "VectorRecord":
        """Build a VectorRecord from a pgvector search row (embedding not returned)."""
        metadata = dict(row.get("meta") or {})
        if row.get("score") is not None:
            metadata["similarity_score"] = float(row["score"])
        return VectorRecord(
            vector_id=row.get("vector_id", ""),
            doc_id=row.get("doc_id", ""),
            tenant_id=row.get("tenant_id", ""),
            user_id=row.get("user_id", ""),
            source=row.get("source", ""),
            external_id=row.get("external_id", ""),
            text=row.get("text", ""),
            vector=[],
            acl=list(row.get("acl") or []),
            chunk_index=row.get("chunk_index", 0),
            doc_ref_id=row.get("doc_ref_id", ""),
            prev_chunk_id=row.get("prev_chunk_id"),
            next_chunk_id=row.get("next_chunk_id"),
            total_chunks=row.get("total_chunks", 0),
            metadata=metadata,
        )

    def upsert_vectors(self, embedded_chunks: list[Any]) -> int:
        count = 0
        records: list[VectorRecord] = []
        for item in embedded_chunks:
            node = item.node
            vector = item.vector
            doc_ref = getattr(node, "doc_ref_id", None) or getattr(node, "external_id", "") or node.doc_id
            prev_id = getattr(node, "prev_chunk_id", None)
            next_id = getattr(node, "next_chunk_id", None)
            tot = getattr(node, "total_chunks", 0)

            rec = VectorRecord(
                vector_id=node.chunk_id,
                doc_id=node.doc_id,
                tenant_id=node.tenant_id,
                user_id=node.user_id,
                source=node.source,
                external_id=node.external_id,
                text=node.text,
                vector=vector,
                acl=list(node.acl),
                chunk_index=node.chunk_index,
                doc_ref_id=doc_ref,
                prev_chunk_id=prev_id,
                next_chunk_id=next_id,
                total_chunks=tot,
                metadata=node.metadata,
            )
            self._in_memory[node.chunk_id] = rec
            records.append(rec)
            count += 1

        # pgvector is the chunk store: it serves both search and the chunk viewer.
        indexed = 0
        if pgvector_index is not None and records:
            indexed = pgvector_index.upsert(records)
            if indexed:
                print(f"[VectorStore] Indexed {indexed} embeddings into pgvector (HNSW).")

        # MongoDB only carries chunks when pgvector is unavailable, so the same
        # embeddings are never stored twice.
        if indexed == 0 and self._collection is not None:
            for rec in records:
                try:
                    self._collection.update_one(
                        {"vector_id": rec.vector_id},
                        {"$set": rec.to_dict()},
                        upsert=True,
                    )
                except Exception as err:
                    print(f"[VectorStore] Mongo vector upsert error: {err}")

        destination = "pgvector" if indexed else "MongoDB fallback"
        print(f"[VectorStore] Upserted {count} vector records into VectorStore ({destination}).")
        return count

    def count_vectors(self, tenant_id: str, source: str, user_id: str = "") -> int:
        """Returns accurate count of stored vector records across MongoDB and memory."""
        if self._collection is not None:
            try:
                query: dict[str, Any] = {"tenant_id": tenant_id, "source": source.lower()}
                if user_id:
                    query["user_id"] = user_id
                cnt = self._collection.count_documents(query)
                if cnt > 0:
                    return cnt
            except Exception as err:
                print(f"[VectorStore] Mongo count error: {err}")

        return sum(
            1 for rec in self._in_memory.values()
            if rec.tenant_id == tenant_id and rec.source.lower() == source.lower() and (not user_id or rec.user_id == user_id)
        )

    def delete_by_doc_id(self, doc_id: str) -> int:
        to_delete = [vid for vid, rec in self._in_memory.items() if rec.doc_id == doc_id]
        for vid in to_delete:
            self._in_memory.pop(vid, None)

        mongo_deleted = 0
        if self._collection is not None:
            try:
                r = self._collection.delete_many({"doc_id": doc_id})
                mongo_deleted = r.deleted_count
            except Exception as err:
                print(f"[VectorStore] Mongo delete by doc_id error: {err}")

        if pgvector_index is not None:
            pgvector_index.delete_by_doc_id(doc_id)

        count = max(len(to_delete), mongo_deleted)
        print(f"[VectorStore] Purged {count} vectors for doc_id={doc_id}.")
        return count

    def delete_by_tenant_source_user(self, tenant_id: str, source: str, user_id: str = "") -> int:
        to_delete = [
            vid for vid, rec in self._in_memory.items()
            if rec.tenant_id == tenant_id and rec.source.lower() == source.lower() and (not user_id or rec.user_id == user_id)
        ]
        for vid in to_delete:
            self._in_memory.pop(vid, None)

        mongo_deleted = 0
        if self._collection is not None:
            try:
                query: dict[str, Any] = {"tenant_id": tenant_id, "source": source.lower()}
                if user_id:
                    query["user_id"] = user_id
                r = self._collection.delete_many(query)
                mongo_deleted = r.deleted_count
            except Exception as err:
                print(f"[VectorStore] Mongo purge error: {err}")

        if pgvector_index is not None:
            pgvector_index.delete_by_tenant_source_user(tenant_id, source, user_id)

        count = max(len(to_delete), mongo_deleted)
        print(f"[VectorStore] Purged {count} vectors for tenant={tenant_id}, source={source}, user={user_id}.")
        return count

    def update_acl_for_doc_id(self, doc_id: str, new_acl: list[str]) -> int:
        count = 0
        for rec in self._in_memory.values():
            if rec.doc_id == doc_id:
                rec.acl = list(new_acl)
                rec.updated_at = datetime.now(timezone.utc)
                count += 1

        if self._collection is not None:
            try:
                self._collection.update_many(
                    {"doc_id": doc_id},
                    {"$set": {"acl": list(new_acl), "updated_at": datetime.now(timezone.utc).isoformat()}}
                )
            except Exception as err:
                print(f"[VectorStore] Mongo ACL update error: {err}")

        if pgvector_index is not None:
            pgvector_index.update_acl_for_doc_id(doc_id, list(new_acl))

        print(f"[VectorStore] Updated ACLs for {count} vectors under doc_id={doc_id}.")
        return count

    def search_similarity(
        self,
        query_vector: list[float],
        tenant_id: str,
        user_acl: list[str],
        limit: int = 5,
        min_score: float = 0.0,
    ) -> list[VectorRecord]:
        """ACL-filtered cosine-similarity search.

        Ranks candidate chunks by cosine similarity to ``query_vector`` (real
        semantic ranking) after a security ACL pre-filter. Reads from the
        persistent Mongo collection when available, else the in-memory store.

        NOTE: this is a brute-force scan (no native vector index — self-hosted
        Mongo has no $vectorSearch). Correct and fine at current volume; a
        pgvector/Atlas index is required to scale.
        """
        # Prefer the HNSW index: tenant and ACL filtering run in SQL and only the
        # top-k rows come back, instead of scanning every chunk in Python.
        if pgvector_index is not None and query_vector:
            rows = pgvector_index.search(
                query_vector=query_vector,
                tenant_id=tenant_id,
                user_acl=list(user_acl),
                limit=limit,
                min_score=min_score,
            )
            if rows is not None:
                return [self._record_from_row(row) for row in rows]

        user_set = set(user_acl)
        candidates: list[VectorRecord] = []

        if self._collection is not None:
            try:
                cursor = self._collection.find({"tenant_id": tenant_id})
                for data in cursor:
                    rec = VectorRecord.from_dict(data)
                    if user_set.intersection(set(rec.acl)):
                        candidates.append(rec)
            except Exception as err:
                print(f"[VectorStore] Mongo similarity scan error: {err}")
                candidates = []

        if not candidates:
            for rec in self._in_memory.values():
                if rec.tenant_id == tenant_id and user_set.intersection(set(rec.acl)):
                    candidates.append(rec)

        # If no usable query vector was supplied, preserve prior behaviour
        # (return ACL-filtered candidates unranked).
        if not query_vector:
            return candidates[:limit]

        scored = [(_cosine_similarity(query_vector, rec.vector), rec) for rec in candidates]
        scored = [(s, rec) for s, rec in scored if s >= min_score]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [rec for _, rec in scored[:limit]]
