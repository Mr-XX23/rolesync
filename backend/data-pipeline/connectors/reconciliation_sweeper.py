from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from connectors.events.canonical_event import CanonicalEvent, EventType
from pipeline.canonical_store import CanonicalStore
from connectors.deletion_handler import DeletionHandler
from connectors.acl_sync import ACLSyncService

@dataclass
class ReconciliationReport:
    total_checked: int
    missed_deletions_found: int
    acl_drift_found: int
    corrections_applied: int

class ReconciliationSweeper:
    """Periodic Reconciliation Sweeper catching missed webhooks and permission drift."""

    def __init__(
        self,
        store: CanonicalStore | None = None,
        deletion_handler: DeletionHandler | None = None,
        acl_sync: ACLSyncService | None = None,
    ) -> None:
        self.store = store or CanonicalStore()
        self.deletion_handler = deletion_handler or DeletionHandler(self.store)
        self.acl_sync = acl_sync or ACLSyncService(self.store)

    def sweep_source(self, tenant_id: str, source: str, live_source_docs: list[dict[str, Any]]) -> ReconciliationReport:
        print(f"[ReconciliationSweeper] Starting sweep for tenant_id={tenant_id}, source={source}...")
        
        live_doc_map = {doc["external_id"]: doc for doc in live_source_docs}
        missed_deletions = 0
        acl_drift = 0
        corrections = 0
        total_checked = 0

        # Compare existing records in Canonical Store for this tenant & source
        for doc_id, record in list(self.store._records.items()):
            if record.tenant_id != tenant_id or record.source != source or record.status == "DELETED":
                continue

            total_checked += 1
            external_id = record.external_id

            # 1. Check for missed deletion
            if external_id not in live_doc_map:
                missed_deletions += 1
                print(f"[ReconciliationSweeper] Missed deletion detected for doc_id={doc_id}! Applying tombstone.")
                event = CanonicalEvent(
                    event_id=f"reconcile_del_{external_id}",
                    event_type=EventType.DELETE,
                    source=source,
                    tenant_id=tenant_id,
                    user_id=record.user_id,
                    external_id=external_id,
                    raw_ref={},
                    acl=record.acl,
                    timestamp=datetime.now(timezone.utc),
                )
                if self.deletion_handler.process_deletion(event):
                    corrections += 1

            # 2. Check for ACL drift
            else:
                live_doc = live_doc_map[external_id]
                live_acl = live_doc.get("acl", [])
                if set(record.acl) != set(live_acl):
                    acl_drift += 1
                    print(f"[ReconciliationSweeper] ACL drift detected for doc_id={doc_id}! Current={record.acl}, Live={live_acl}")
                    event = CanonicalEvent(
                        event_id=f"reconcile_acl_{external_id}",
                        event_type=EventType.ACL_CHANGE,
                        source=source,
                        tenant_id=tenant_id,
                        user_id=record.user_id,
                        external_id=external_id,
                        raw_ref={},
                        acl=live_acl,
                        timestamp=datetime.now(timezone.utc),
                    )
                    if self.acl_sync.process_acl_change(event):
                        corrections += 1

        report = ReconciliationReport(
            total_checked=total_checked,
            missed_deletions_found=missed_deletions,
            acl_drift_found=acl_drift,
            corrections_applied=corrections,
        )
        print(f"[ReconciliationSweeper] Sweep complete for {source}: Checked={report.total_checked}, Missed Deletes={report.missed_deletions_found}, ACL Drift={report.acl_drift_found}, Corrections={report.corrections_applied}")
        return report
