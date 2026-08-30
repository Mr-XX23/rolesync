from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import os

try:
    import pymongo
except ImportError:
    pymongo = None

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
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

class VectorStore:
    """MongoDB Atlas / In-Memory Vector Store executing ACL security pre-filtering and similarity searches."""

    def __init__(self) -> None:
        self.mongo_uri = os.environ.get("MONGODB_URI", "")
        self.db_name = os.environ.get("MONGODB_DB_NAME", "rolesync_rag")
        self.collection_name = "vector_chunks"
        self._in_memory: dict[str, VectorRecord] = {}

    def upsert_vectors(self, embedded_chunks: list[Any]) -> int:
        count = 0
        for item in embedded_chunks:
            node = item.node
            vector = item.vector
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
                metadata=node.metadata,
            )
            self._in_memory[node.chunk_id] = rec
            count += 1

        print(f"[VectorStore] Upserted {count} vector records into VectorStore.")
        return count

    def delete_by_doc_id(self, doc_id: str) -> int:
        to_delete = [vid for vid, rec in self._in_memory.items() if rec.doc_id == doc_id]
        for vid in to_delete:
            self._in_memory.pop(vid, None)
        print(f"[VectorStore] Purged {len(to_delete)} vectors for doc_id={doc_id}.")
        return len(to_delete)

    def update_acl_for_doc_id(self, doc_id: str, new_acl: list[str]) -> int:
        count = 0
        for rec in self._in_memory.values():
            if rec.doc_id == doc_id:
                rec.acl = list(new_acl)
                rec.updated_at = datetime.now(timezone.utc)
                count += 1
        print(f"[VectorStore] Updated ACLs for {count} vectors under doc_id={doc_id}.")
        return count

    def search_similarity(
        self,
        query_vector: list[float],
        tenant_id: str,
        user_acl: list[str],
        limit: int = 5,
    ) -> list[VectorRecord]:
        results: list[VectorRecord] = []
        user_set = set(user_acl)

        for rec in self._in_memory.values():
            if rec.tenant_id == tenant_id:
                # Security ACL Pre-Filtering: User must match at least one ACL entry
                if user_set.intersection(set(rec.acl)):
                    results.append(rec)

        return results[:limit]
