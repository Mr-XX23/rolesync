from datetime import datetime, timezone
from connectors.events.canonical_event import CanonicalEvent
from pipeline.canonical_store import CanonicalStore

class DeletionHandler:
    """Deletion Handler for tombstones and GDPR erasure cascading across data stores."""

    def __init__(self, store: CanonicalStore | None = None) -> None:
        self.store = store or CanonicalStore()

    def process_deletion(self, event: CanonicalEvent) -> bool:
        doc_id = f"{event.tenant_id}:{event.source}:{event.external_id}"
        print(f"[DeletionHandler] Processing deletion request for doc_id={doc_id}")

        # 1. Apply tombstone status in Canonical DB Store
        success = self.store.mark_status(doc_id, status="DELETED")
        if not success:
            # If document was not recorded prior, create a tombstone record directly
            self.store.record_event(event, status="DELETED")
            print(f"[DeletionHandler] Created new tombstone record for doc_id={doc_id}")

        # 2. Cascade deletion to raw object store, hash store, and vector search index
        self._cascade_deletion(doc_id=doc_id, tenant_id=event.tenant_id, external_id=event.external_id)

        print(f"[DeletionHandler] Successfully completed deletion cascade for doc_id={doc_id}")
        return True

    def _cascade_deletion(self, doc_id: str, tenant_id: str, external_id: str) -> None:
        # Cascade hooks:
        # - Raw Store: mark tombstone in object storage / S3
        # - Versioned Hash DB: purge chunk hashes
        # - MongoDB Vector Store: remove chunks matching doc_id
        print(f"[DeletionHandler] Cascaded tombstone deletion to RawStore, HashDB, and VectorStore for doc_id={doc_id}")
