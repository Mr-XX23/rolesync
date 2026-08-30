from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent, EventType
from module_1_document_processing.pipeline.canonical_store import CanonicalStore
from module_1_document_processing.del_acl_and_reconc.deletion_handler import DeletionHandler
from module_1_document_processing.del_acl_and_reconc.acl_sync import ACLSyncService

@dataclass
class SweepReport:
    tenant_id: str
    source: str
    total_checked: int = 0
    missed_deletions_found: int = 0
    acl_drift_found: int = 0
    corrections_applied: int = 0

class ReconciliationSweeper:
    """Reconciliation Sweeper finding missed deletions and permission drifts against live source APIs."""

    def __init__(
        self,
        canonical_store: CanonicalStore | None = None,
        deletion_handler: DeletionHandler | None = None,
        acl_sync: ACLSyncService | None = None,
    ) -> None:
        self.canonical_store = canonical_store or CanonicalStore()
        self.deletion_handler = deletion_handler or DeletionHandler(self.canonical_store)
        self.acl_sync = acl_sync or ACLSyncService(self.canonical_store)

    def sweep_source(self, tenant_id: str, source: str, live_source_docs: list[dict[str, Any]]) -> SweepReport:
        print(f"[ReconciliationSweeper] Starting sweep for tenant_id={tenant_id}, source={source}...")
        report = SweepReport(tenant_id=tenant_id, source=source)

        live_doc_map = {doc["external_id"]: doc for doc in live_source_docs if "external_id" in doc}
        
        # Check all indexed documents for this tenant & source
        indexed_docs = [
            doc for doc in self.canonical_store._store.values()
            if doc.tenant_id == tenant_id and doc.source == source and doc.status != "DELETED"
        ]

        report.total_checked = len(indexed_docs)

        for doc in indexed_docs:
            if doc.external_id not in live_doc_map:
                # 1. Missed Deletion Detected
                print(f"[ReconciliationSweeper] Missed deletion detected for doc_id={doc.doc_id}! Applying tombstone.")
                report.missed_deletions_found += 1
                del_event = CanonicalEvent(
                    event_id=f"recon_del_{doc.external_id}",
                    event_type=EventType.DELETE,
                    source=source,
                    tenant_id=tenant_id,
                    user_id=doc.user_id,
                    external_id=doc.external_id,
                    raw_ref={},
                    acl=doc.acl,
                    timestamp=datetime.now(timezone.utc),
                )
                self.deletion_handler.process_deletion(del_event)
                report.corrections_applied += 1
            else:
                live_item = live_doc_map[doc.external_id]
                live_acl = live_item.get("acl", [])
                if set(doc.acl) != set(live_acl):
                    # 2. ACL Permission Drift Detected
                    print(f"[ReconciliationSweeper] ACL drift detected for doc_id={doc.doc_id}! Current={doc.acl}, Live={live_acl}")
                    report.acl_drift_found += 1
                    acl_event = CanonicalEvent(
                        event_id=f"recon_acl_{doc.external_id}",
                        event_type=EventType.ACL_CHANGE,
                        source=source,
                        tenant_id=tenant_id,
                        user_id=doc.user_id,
                        external_id=doc.external_id,
                        raw_ref={},
                        acl=live_acl,
                        timestamp=datetime.now(timezone.utc),
                    )
                    self.acl_sync.process_acl_change(acl_event)
                    report.corrections_applied += 1

        print(
            f"[ReconciliationSweeper] Sweep complete for {source}: Checked={report.total_checked}, "
            f"Missed Deletes={report.missed_deletions_found}, ACL Drift={report.acl_drift_found}, Corrections={report.corrections_applied}"
        )
        return report
