"""Finds missed deletions and permission drift by diffing a live source against
the canonical store.

This is how deletions and ACL changes are actually detected: providers do not
reliably emit those events through Composio, so the canonical record is
reconciled against reality on a schedule instead.

Two safety rules govern tombstoning, because a wrong answer here destroys data:
  1. An INCOMPLETE listing (failed call, truncated page, unbounded source)
     never implies deletion - absence is only meaningful in a complete listing.
  2. A sweep that would tombstone more than `max_delete_ratio` of a tenant's
     documents is refused outright and reported, rather than cascading.
ACL fixes are always safe to apply: they only touch documents the source
confirmed exist, and only when the provider actually reported permissions.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent, EventType
from module_1_document_processing.del_acl_and_reconc.acl_sync import ACLSyncService
from module_1_document_processing.del_acl_and_reconc.deletion_handler import DeletionHandler
from module_1_document_processing.pipeline.canonical_store import CanonicalStore

# Below this many documents the ratio guard is not meaningful (deleting 1 of 2
# is a legitimate, common case).
MIN_DOCS_FOR_RATIO_GUARD = 5


def _default_max_delete_ratio() -> float:
    try:
        value = float(os.environ.get("RECONCILIATION_MAX_DELETE_RATIO", "") or 0.5)
        return value if 0 < value <= 1 else 0.5
    except (TypeError, ValueError):
        return 0.5


@dataclass
class SweepReport:
    tenant_id: str
    source: str
    total_checked: int = 0
    missed_deletions_found: int = 0
    acl_drift_found: int = 0
    corrections_applied: int = 0
    skipped_deletions: int = 0
    aborted: bool = False
    reason: str = ""


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

    def sweep_source(
        self,
        tenant_id: str,
        source: str,
        live_source_docs: list[dict[str, Any]],
        complete: bool = True,
        max_delete_ratio: Optional[float] = None,
    ) -> SweepReport:
        print(f"[ReconciliationSweeper] Starting sweep for tenant_id={tenant_id}, source={source}...")
        report = SweepReport(tenant_id=tenant_id, source=source)

        live_doc_map = {doc["external_id"]: doc for doc in live_source_docs if "external_id" in doc}

        indexed_docs = self.canonical_store.list_documents(
            tenant_id=tenant_id,
            source=source,
            exclude_statuses=("DELETED",),
        )
        report.total_checked = len(indexed_docs)

        missing = [doc for doc in indexed_docs if doc.external_id not in live_doc_map]
        report.missed_deletions_found = len(missing)

        allow_deletions = True

        # Rule 1: absence only means deletion when the listing is exhaustive.
        if not complete:
            allow_deletions = False
            if missing:
                report.reason = "listing incomplete - deletions not applied"
                print(
                    f"[ReconciliationSweeper] Listing for {source} was incomplete; "
                    f"skipping {len(missing)} candidate deletion(s) to avoid false tombstones."
                )

        # Rule 2: refuse a mass tombstone even on a 'complete' listing.
        ratio = max_delete_ratio if max_delete_ratio is not None else _default_max_delete_ratio()
        if (
            allow_deletions
            and report.total_checked >= MIN_DOCS_FOR_RATIO_GUARD
            and len(missing) > report.total_checked * ratio
        ):
            allow_deletions = False
            report.aborted = True
            report.reason = (
                f"refused to tombstone {len(missing)}/{report.total_checked} documents "
                f"(exceeds {ratio:.0%} safety limit)"
            )
            print(f"[ReconciliationSweeper] ABORTED deletions for {source}: {report.reason}")

        if not allow_deletions:
            report.skipped_deletions = len(missing)

        for doc in indexed_docs:
            if doc.external_id not in live_doc_map:
                if not allow_deletions:
                    continue
                print(f"[ReconciliationSweeper] Missed deletion detected for doc_id={doc.doc_id}! Applying tombstone.")
                self.deletion_handler.process_deletion(
                    CanonicalEvent(
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
                )
                report.corrections_applied += 1
                continue

            live_item = live_doc_map[doc.external_id]
            # A provider that does not report permissions must not be read as
            # "nobody has access" - only compare when acl was actually returned.
            if "acl" not in live_item:
                continue

            live_acl = live_item.get("acl") or []
            if set(doc.acl) != set(live_acl):
                print(
                    f"[ReconciliationSweeper] ACL drift detected for doc_id={doc.doc_id}! "
                    f"Current={doc.acl}, Live={live_acl}"
                )
                report.acl_drift_found += 1
                self.acl_sync.process_acl_change(
                    CanonicalEvent(
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
                )
                report.corrections_applied += 1

        print(
            f"[ReconciliationSweeper] Sweep complete for {source}: Checked={report.total_checked}, "
            f"Missed Deletes={report.missed_deletions_found}, ACL Drift={report.acl_drift_found}, "
            f"Corrections={report.corrections_applied}, Skipped Deletes={report.skipped_deletions}"
        )
        return report
