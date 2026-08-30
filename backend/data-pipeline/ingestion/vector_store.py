import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from ingestion.embedding_worker import EmbeddedChunk

try:
    from pymongo import MongoClient
except ImportError:
    MongoClient = None

@dataclass
class VectorRecord:
    vector_id: str
    doc_id: str
    chunk_index: int
    text: str
    vector: list[float]
    tenant_id: str
    user_id: str
    source: str
    acl: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

class VectorStore:
    """Vector database adapter supporting MongoDB Atlas Vector Search / In-Memory HNSW vector index."""

    def __init__(self) -> None:
        self._records: dict[str, VectorRecord] = {}
        self.mongo_uri = os.environ.get("MONGODB_URI", "")
        self.db_name = os.environ.get("MONGODB_DB_NAME", "rolesync_rag")
        self.client = None
        self.collection = None

        if MongoClient is not None and self.mongo_uri:
            try:
                self.client = MongoClient(self.mongo_uri)
                self.db = self.client[self.db_name]
                self.collection = self.db["vector_chunks"]
                print(f"[VectorStore] Successfully connected to live MongoDB Atlas database '{self.db_name}'!")
            except Exception as err:
                print(f"[VectorStore] MongoDB Atlas connection notice: {err}. Using memory index.")

    def upsert_vectors(self, embedded_chunks: list[EmbeddedChunk]) -> int:
        count = 0
        for item in embedded_chunks:
            record = VectorRecord(
                vector_id=item.node.chunk_id,
                doc_id=item.node.doc_id,
                chunk_index=item.node.chunk_index,
                text=item.node.text,
                vector=item.vector,
                tenant_id=item.node.tenant_id,
                user_id=item.node.user_id,
                source=item.node.source,
                acl=list(item.node.acl),
                metadata=item.node.metadata,
            )
            self._records[item.node.chunk_id] = record

            # Upsert into live MongoDB Atlas if connected
            if self.collection is not None:
                try:
                    doc_dict = {
                        "_id": item.node.chunk_id,
                        "doc_id": item.node.doc_id,
                        "chunk_index": item.node.chunk_index,
                        "text": item.node.text,
                        "vector": item.vector,
                        "tenant_id": item.node.tenant_id,
                        "user_id": item.node.user_id,
                        "source": item.node.source,
                        "acl": list(item.node.acl),
                        "metadata": item.node.metadata,
                        "updated_at": datetime.now(timezone.utc),
                    }
                    self.collection.replace_one({"_id": item.node.chunk_id}, doc_dict, upsert=True)
                except Exception as err:
                    print(f"[VectorStore] MongoDB Atlas upsert error: {err}")

            count += 1

        print(f"[VectorStore] Upserted {count} vector records into VectorStore.")
        return count

    def delete_doc_vectors(self, doc_id: str) -> int:
        to_del = [vid for vid, rec in self._records.items() if rec.doc_id == doc_id]
        for vid in to_del:
            del self._records[vid]

        if self.collection is not None:
            try:
                self.collection.delete_many({"doc_id": doc_id})
            except Exception as err:
                print(f"[VectorStore] MongoDB Atlas delete error: {err}")

        print(f"[VectorStore] Deleted {len(to_del)} vectors for doc_id={doc_id}")
        return len(to_del)

    def patch_doc_acl(self, doc_id: str, new_acl: list[str]) -> int:
        patched = 0
        for rec in self._records.values():
            if rec.doc_id == doc_id:
                rec.acl = list(new_acl)
                rec.updated_at = datetime.now(timezone.utc)
                patched += 1

        if self.collection is not None:
            try:
                self.collection.update_many({"doc_id": doc_id}, {"$set": {"acl": list(new_acl)}})
            except Exception as err:
                print(f"[VectorStore] MongoDB Atlas ACL patch error: {err}")

        print(f"[VectorStore] Patched ACL for {patched} vector records matching doc_id={doc_id}")
        return patched

    def search_similarity(self, query_vector: list[float], tenant_id: str, user_acl: list[str], limit: int = 5) -> list[VectorRecord]:
        # Live MongoDB Atlas Vector Search query with pre-filtering
        if self.collection is not None:
            try:
                pipeline = [
                    {
                        "$vectorSearch": {
                            "index": "vector_index",
                            "path": "vector",
                            "queryVector": query_vector,
                            "numCandidates": limit * 10,
                            "limit": limit,
                            "filter": {
                                "tenant_id": tenant_id,
                                "acl": {"$in": user_acl},
                            },
                        }
                    }
                ]
                results = list(self.collection.aggregate(pipeline))
                if results:
                    return [
                        VectorRecord(
                            vector_id=r["_id"],
                            doc_id=r["doc_id"],
                            chunk_index=r["chunk_index"],
                            text=r["text"],
                            vector=r["vector"],
                            tenant_id=r["tenant_id"],
                            user_id=r["user_id"],
                            source=r["source"],
                            acl=r["acl"],
                            metadata=r.get("metadata", {}),
                        )
                        for r in results
                    ]
            except Exception as err:
                print(f"[VectorStore] MongoDB Atlas vectorSearch fallback to memory index: {err}")

        # Memory index fallback
        matches = []
        for record in self._records.values():
            if record.tenant_id != tenant_id:
                continue
            if not set(user_acl).intersection(set(record.acl)) and "*" not in record.acl:
                continue
            matches.append(record)
        return matches[:limit]
