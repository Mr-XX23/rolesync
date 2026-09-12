"""Reconciliation must never tombstone documents on weak evidence.

A sweep decides what to DELETE, so these pin the guards: an incomplete listing
proves nothing, a mass deletion is refused, and a provider that omits
permissions must not be read as "nobody has access".
"""
from datetime import datetime, timezone

from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent, EventType
from module_1_document_processing.del_acl_and_reconc.acl_sync import ACLSyncService
from module_1_document_processing.del_acl_and_reconc.deletion_handler import DeletionHandler
from module_1_document_processing.del_acl_and_reconc.live_source_lister import (
    SWEEPABLE_SOURCES,
    LiveListing,
    LiveSourceLister,
)
from module_1_document_processing.del_acl_and_reconc.reconciliation_sweeper import ReconciliationSweeper
from module_1_document_processing.pipeline.canonical_store import CanonicalStore

TENANT = "tenant_recon"
SOURCE = "gdrive"


def _seed(store: CanonicalStore, external_ids, acl=("u1@example.com",)):
    for ext in external_ids:
        store.record_event(
            CanonicalEvent(
                event_id=f"evt_{ext}", event_type=EventType.CREATE, source=SOURCE,
                tenant_id=TENANT, user_id="u1", external_id=ext, raw_ref={},
                acl=list(acl), timestamp=datetime.now(timezone.utc),
            ),
            status="PARSED_SUCCESS",
        )


def _sweeper(store):
    return ReconciliationSweeper(store, DeletionHandler(store), ACLSyncService(store))


def test_incomplete_listing_never_deletes():
    store = CanonicalStore()
    _seed(store, ["f1", "f2"])

    report = _sweeper(store).sweep_source(TENANT, SOURCE, live_source_docs=[], complete=False)

    assert report.missed_deletions_found == 2, "absences should still be detected"
    assert report.corrections_applied == 0, "but nothing may be tombstoned"
    assert report.skipped_deletions == 2
    assert store.get_document(f"{TENANT}:{SOURCE}:f1").status != "DELETED"


def test_mass_deletion_is_refused():
    store = CanonicalStore()
    _seed(store, [f"f{i}" for i in range(6)])

    # Only one of six survives at the source -> 83% deletion, over the 50% limit.
    report = _sweeper(store).sweep_source(
        TENANT, SOURCE, live_source_docs=[{"external_id": "f0"}], complete=True
    )

    assert report.aborted is True
    assert report.corrections_applied == 0
    assert report.skipped_deletions == 5
    assert "safety limit" in report.reason
    assert store.get_document(f"{TENANT}:{SOURCE}:f3").status != "DELETED"


def test_deletion_applied_when_listing_is_complete_and_modest():
    store = CanonicalStore()
    _seed(store, ["keep", "gone"])

    report = _sweeper(store).sweep_source(
        TENANT, SOURCE, live_source_docs=[{"external_id": "keep"}], complete=True
    )

    assert report.aborted is False
    assert report.corrections_applied == 1
    assert store.get_document(f"{TENANT}:{SOURCE}:gone").status == "DELETED"
    assert store.get_document(f"{TENANT}:{SOURCE}:keep").status != "DELETED"


def test_missing_acl_field_does_not_rewrite_permissions():
    store = CanonicalStore()
    _seed(store, ["f1"], acl=["u1@example.com", "u2@example.com"])

    # Provider returned the file but reported no permissions at all.
    report = _sweeper(store).sweep_source(
        TENANT, SOURCE, live_source_docs=[{"external_id": "f1"}], complete=True
    )

    assert report.acl_drift_found == 0
    assert "u2@example.com" in store.get_document(f"{TENANT}:{SOURCE}:f1").acl


def test_reported_acl_drift_is_corrected():
    store = CanonicalStore()
    _seed(store, ["f1"], acl=["u1@example.com"])

    report = _sweeper(store).sweep_source(
        TENANT,
        SOURCE,
        live_source_docs=[{"external_id": "f1", "acl": ["u1@example.com", "u9@example.com"]}],
        complete=True,
    )

    assert report.acl_drift_found == 1
    assert "u9@example.com" in store.get_document(f"{TENANT}:{SOURCE}:f1").acl


def test_unbounded_sources_are_not_sweepable():
    """Mailboxes and chat histories cannot prove deletion from a partial page."""
    assert "gmail" not in SWEEPABLE_SOURCES
    assert "slack" not in SWEEPABLE_SOURCES

    listing = LiveSourceLister(composio_client=None).list_source("gmail", "u1")
    assert isinstance(listing, LiveListing)
    assert listing.complete is False
    assert listing.items == []


def test_failed_listing_is_marked_incomplete():
    class _Boom:
        class _composio:
            class tools:
                @staticmethod
                def execute(**_kwargs):
                    raise RuntimeError("composio down")

    listing = LiveSourceLister(_Boom()).list_source("gdrive", "u1")
    assert listing.complete is False
    assert listing.items == []
