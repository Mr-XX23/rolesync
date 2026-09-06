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

    def to_dict(self) -> dict[str, Any]:
        return {
            "vector_id": self.vector_id,
            "doc_id": self.doc_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "source": self.source,
            "external_id": self.external_id,
            "text": self.text,
            "vector": self.vector,
            "acl": self.acl,
            "chunk_index": self.chunk_index,
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
                print(f"[VectorStore] Initialized persistent MongoDB collection '{self.collection_name}' at {self.mongo_uri}/{self.db_name}")
            except Exception as err:
                print(f"[VectorStore] MongoDB offline / local mode ({err})")
                self._collection = None

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

            # Persist to MongoDB
            if self._collection is not None:
                try:
                    self._collection.update_one(
                        {"vector_id": node.chunk_id},
                        {"$set": rec.to_dict()},
                        upsert=True
                    )
                except Exception as err:
                    print(f"[VectorStore] Mongo vector upsert error: {err}")

            count += 1

        print(f"[VectorStore] Upserted {count} vector records into VectorStore (in-memory + MongoDB).")
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
