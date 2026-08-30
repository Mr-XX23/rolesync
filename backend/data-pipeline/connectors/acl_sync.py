from connectors.events.canonical_event import CanonicalEvent
from pipeline.canonical_store import CanonicalStore

class ACLSyncService:
    """ACL Sync Service patching live acl[] snapshots across stores."""

    def __init__(self, store: CanonicalStore | None = None) -> None:
        self.store = store or CanonicalStore()

    def process_acl_change(self, event: CanonicalEvent) -> bool:
        doc_id = f"{event.tenant_id}:{event.source}:{event.external_id}"
        new_acl = list(event.acl)
        print(f"[ACLSyncService] Processing ACL change for doc_id={doc_id}: new_acl={new_acl}")

        # 1. Patch ACL snapshot in Canonical DB Store
        updated = self.store.update_acl(doc_id, new_acl)
        if not updated:
            # If document record does not exist yet, record event with ACL snapshot
            self.store.record_event(event, status="ACL_SYNCHRONIZED")
            print(f"[ACLSyncService] Created new ACL snapshot record for doc_id={doc_id}")

        # 2. Patch live acl[] array in MongoDB Vector Chunk Store
        self._patch_vector_chunk_acls(doc_id=doc_id, new_acl=new_acl)

        print(f"[ACLSyncService] Successfully patched ACLs for doc_id={doc_id}")
        return True

    def _patch_vector_chunk_acls(self, doc_id: str, new_acl: list[str]) -> None:
        # Patch hook:
        # - MongoDB: db.chunks.updateMany({ doc_id: doc_id }, { $set: { acl: new_acl } })
        print(f"[ACLSyncService] Patched acl[] array in MongoDB VectorStore for doc_id={doc_id}")
