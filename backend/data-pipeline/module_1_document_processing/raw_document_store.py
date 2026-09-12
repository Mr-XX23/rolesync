from __future__ import annotations
import base64
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from module_1_document_processing.raw_object_store import raw_object_store

try:
    import pymongo
except ImportError:
    pymongo = None


class RawDocumentStore:
    """
    Dedicated storage manager for complete, unfragmented collateral documents.
    Stores the full parsed markdown/text content, metadata taxonomy, and persists
    the raw binary file to disk and/or MongoDB.
    """

    def __init__(
        self,
        mongo_uri: Optional[str] = None,
        db_name: Optional[str] = None,
        storage_dir: Optional[str] = None,
    ) -> None:
        self.mongo_uri = mongo_uri or os.environ.get("MONGODB_URI", "mongodb://mongodb:27017")
        self.db_name = db_name or os.environ.get("MONGODB_DB_NAME", "rolesync_rag")
        self.storage_dir = Path(
            storage_dir
            or os.environ.get(
                "VAULT_STORAGE_DIR",
                os.path.join(os.path.dirname(__file__), "..", "storage", "vault_files"),
            )
        )
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self._in_memory: dict[str, dict[str, Any]] = {}
        self._collection = None

        if pymongo and self.mongo_uri:
            try:
                client = pymongo.MongoClient(self.mongo_uri, serverSelectionTimeoutMS=500)
                client.admin.command("ping")
                self._collection = client[self.db_name]["raw_documents"]
                self._collection.create_index([("doc_ref_id", pymongo.ASCENDING)], unique=True)
                self._collection.create_index([("tenant_id", pymongo.ASCENDING), ("user_id", pymongo.ASCENDING)])
                self._collection.create_index([("category", pymongo.ASCENDING)])
                print(f"[RawDocumentStore] Connected to MongoDB collection 'raw_documents' at {self.mongo_uri}/{self.db_name}")
            except Exception as err:
                print(f"[RawDocumentStore] MongoDB offline / using local fallback: {err}")
                self._collection = None

    def save_raw_document(
        self,
        doc_ref_id: str,
        tenant_id: str,
        user_id: str,
        filename: str,
        mime_type: str,
        full_text_content: str,
        raw_bytes: Optional[bytes] = None,
        category: str = "GENERAL_RESOURCE",
        document_type: str = "GENERAL_RESOURCE",
        target_competitor: Optional[str] = None,
        target_industry: Optional[str] = None,
        sales_summary: str = "",
        sales_tags: Optional[list[str]] = None,
        total_chunks: int = 0,
        chunk_ids: Optional[list[str]] = None,
        parser_used: str = "local_text",
        parse_status: str = "SUCCESS",
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Saves full document record to MongoDB and saves raw binary to disk."""
        now_str = datetime.now(timezone.utc).isoformat()
        clean_name = re.sub(r"[^\w\-.]", "_", filename)

        # Raw bytes go to the configured object store (MinIO / R2 / S3) with local
        # disk as the automatic fallback, rather than being base64-inlined into
        # MongoDB, which bloated the document collection.
        storage_ref = ""
        if raw_bytes:
            storage_ref = raw_object_store.put(
                f"{tenant_id}/{doc_ref_id}_{clean_name}", raw_bytes, mime_type
            ) or ""

        # Legacy readers expect raw_file_path; keep it populated when the object
        # actually landed on local disk. Object-store records use raw_object_ref.
        file_path_str = storage_ref if storage_ref and not storage_ref.startswith("s3://") else ""

        word_count = len(full_text_content.split()) if full_text_content else 0
        char_count = len(full_text_content) if full_text_content else 0

        doc_record: dict[str, Any] = {
            "doc_ref_id": doc_ref_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "filename": filename,
            "mime_type": mime_type,
            "size_bytes": len(raw_bytes) if raw_bytes else char_count,
            "word_count": word_count,
            "character_count": char_count,
            "category": category,
            "document_type": document_type or category,
            "target_competitor": target_competitor,
            "target_industry": target_industry,
            "sales_summary": sales_summary,
            "sales_tags": sales_tags or [],
            "full_text_content": full_text_content or "",
            "raw_object_ref": storage_ref,
            "raw_file_path": file_path_str,
            # Cleared on re-save so previously inlined blobs stop bloating Mongo.
            "raw_file_base64": None,
            "total_chunks": total_chunks,
            "chunk_ids": chunk_ids or [],
            "parser_used": parser_used,
            "parse_status": parse_status,
            "metadata": metadata or {},
            "created_at": now_str,
            "updated_at": now_str,
        }

        # 3. Persist to MongoDB
        if self._collection is not None:
            try:
                self._collection.update_one(
                    {"doc_ref_id": doc_ref_id},
                    {"$set": doc_record},
                    upsert=True,
                )
            except Exception as err:
                print(f"[RawDocumentStore] Mongo save error for {doc_ref_id}: {err}")

        self._in_memory[doc_ref_id] = doc_record
        print(f"[RawDocumentStore] Saved full document {doc_ref_id} ('{filename}', {word_count} words, {total_chunks} chunks, category={category})")
        return doc_record

    def update_chunks(self, doc_ref_id: str, total_chunks: int, chunk_ids: list[str]) -> None:
        """Updates chunk references after chunking/embedding completes."""
        update_dict = {
            "total_chunks": total_chunks,
            "chunk_ids": chunk_ids,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if self._collection is not None:
            try:
                self._collection.update_one(
                    {"doc_ref_id": doc_ref_id},
                    {"$set": update_dict},
                )
            except Exception as err:
                print(f"[RawDocumentStore] Mongo update chunks error: {err}")

        if doc_ref_id in self._in_memory:
            self._in_memory[doc_ref_id].update(update_dict)

    def get_raw_document(self, doc_ref_id: str) -> Optional[dict[str, Any]]:
        """Retrieves raw document record from Mongo or in-memory cache."""
        if self._collection is not None:
            try:
                doc = self._collection.find_one({"doc_ref_id": doc_ref_id})
                if doc:
                    doc.pop("_id", None)
                    return doc
            except Exception as err:
                print(f"[RawDocumentStore] Mongo read error: {err}")

        return self._in_memory.get(doc_ref_id)

    def get_full_text(self, doc_ref_id: str) -> Optional[str]:
        """Returns the complete unfragmented markdown/text content."""
        doc = self.get_raw_document(doc_ref_id)
        if doc:
            return doc.get("full_text_content", "")
        return None

    def get_raw_file_bytes(self, doc_ref_id: str) -> Optional[tuple[bytes, str, str]]:
        """
        Returns (raw_bytes, filename, mime_type) for downloading or re-processing.
        Attempts disk read first, then Mongo base64 fallback.
        """
        doc = self.get_raw_document(doc_ref_id)
        if not doc:
            return None

        filename = doc.get("filename", "document")
        mime_type = doc.get("mime_type", "application/octet-stream")

        # 1. Object store (MinIO / R2 / S3), or a local path written as a fallback.
        storage_ref = doc.get("raw_object_ref") or ""
        if storage_ref:
            content = raw_object_store.get(storage_ref)
            if content:
                return content, filename, mime_type
            print(f"[RawDocumentStore] Object ref {storage_ref} unreadable; trying legacy locations.")

        # 2. Legacy: file written directly to the storage volume
        file_path = doc.get("raw_file_path")
        if file_path and os.path.exists(file_path):
            try:
                content = Path(file_path).read_bytes()
                return content, filename, mime_type
            except Exception as err:
                print(f"[RawDocumentStore] Disk read error for {file_path}: {err}")

        # 2. Fallback to base64
        b64 = doc.get("raw_file_base64")
        if b64:
            try:
                content = base64.b64decode(b64.encode("utf-8"))
                return content, filename, mime_type
            except Exception as err:
                print(f"[RawDocumentStore] Base64 decode error: {err}")

        # 3. Fallback to full_text_content encoded as utf-8
        text = doc.get("full_text_content")
        if text:
            return text.encode("utf-8", errors="replace"), filename, "text/markdown"

        return None

    def delete_raw_document(self, doc_ref_id: str) -> bool:
        """Deletes raw document from MongoDB, disk, and in-memory cache."""
        doc = self.get_raw_document(doc_ref_id)

        # Remove the stored object first, then any legacy on-disk copy.
        if doc and doc.get("raw_object_ref"):
            raw_object_store.delete(doc["raw_object_ref"])

        if doc and doc.get("raw_file_path") and os.path.exists(doc["raw_file_path"]):
            try:
                os.remove(doc["raw_file_path"])
            except Exception as err:
                print(f"[RawDocumentStore] Error deleting file from disk: {err}")

        if self._collection is not None:
            try:
                self._collection.delete_one({"doc_ref_id": doc_ref_id})
            except Exception as err:
                print(f"[RawDocumentStore] Mongo delete error: {err}")

        self._in_memory.pop(doc_ref_id, None)
        return True


# Global singleton instance
raw_document_store = RawDocumentStore()
