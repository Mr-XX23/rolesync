from dataclasses import dataclass
from typing import Any
from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent
from module_1_document_processing.pipeline.canonical_store import CanonicalStore
from module_3_batch_ingestion_vector.delta_checker import VersionedHashDB
from module_3_batch_ingestion_vector.vector_store import VectorStore

class DeletionHandler:
    """Deletion Handler cascading tombstone deletions across CanonicalStore, Delta HashDB, and VectorStore."""

    def __init__(
        self,
        canonical_store: CanonicalStore | None = None,
        hash_db: VersionedHashDB | None = None,
        vector_store: VectorStore | None = None,
    ) -> None:
        self.canonical_store = canonical_store or CanonicalStore()
        self.hash_db = hash_db or VersionedHashDB()
        self.vector_store = vector_store or VectorStore()

    def process_deletion(self, event: CanonicalEvent) -> bool:
        doc_id = f"{event.tenant_id}:{event.source}:{event.external_id}"
        print(f"[DeletionHandler] Processing deletion request for doc_id={doc_id}")

        # 1. Update CanonicalStore status to DELETED
        staged_doc = self.canonical_store.get_document(doc_id)
        if staged_doc:
            staged_doc.status = "DELETED"
            staged_doc.event_history.append(event)
        else:
            self.canonical_store.record_event(event, status="DELETED")

        # 2. Invalidate Hash DB state for this document
        self.hash_db.clear_document_hashes(doc_id=doc_id)

        # 3. Purge vector embeddings from VectorStore
        deleted_count = self.vector_store.delete_by_doc_id(doc_id=doc_id)

        print(f"[DeletionHandler] Cascaded tombstone deletion to RawStore, HashDB, and VectorStore for doc_id={doc_id}")
        print(f"[DeletionHandler] Successfully completed deletion cascade for doc_id={doc_id}")
        return True
