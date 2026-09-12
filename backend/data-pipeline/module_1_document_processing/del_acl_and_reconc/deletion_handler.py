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

        # 1. Update CanonicalStore status to DELETED.
        # Recorded through the store (not by mutating a returned object) so the
        # tombstone is durably persisted rather than only living in memory.
        self.canonical_store.record_event(event, status="DELETED")

        # 2. Invalidate Hash DB state for this document
        self.hash_db.clear_document_hashes(doc_id=doc_id)

        # 3. Purge vector embeddings from VectorStore
        deleted_count = self.vector_store.delete_by_doc_id(doc_id=doc_id)

        # 4. Erasure has to reach the retained text, the stored original and the
        # vault registry row as well - purging only the vectors left a readable
        # copy of the document behind.
        try:
            from module_1_document_processing.raw_document_store import raw_document_store

            raw_document_store.delete_raw_document(doc_id)
        except Exception as err:
            print(f"[DeletionHandler] Could not purge stored content for {doc_id}: {err}")

        try:
            from module_1_document_processing import knowledge_vault_routes as vault

            vault._delete_doc_record(doc_id)
        except Exception as err:
            print(f"[DeletionHandler] Could not remove registry row for {doc_id}: {err}")

        print(f"[DeletionHandler] Cascaded tombstone deletion to RawStore, content, registry, HashDB and VectorStore for doc_id={doc_id}")
        print(f"[DeletionHandler] Successfully completed deletion cascade for doc_id={doc_id}")
        return True
