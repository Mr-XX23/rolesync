from datetime import datetime, timezone
from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent, EventType
from module_1_document_processing.pipeline.canonical_store import CanonicalStore
from module_1_document_processing.del_acl_and_reconc.deletion_handler import DeletionHandler
from module_1_document_processing.del_acl_and_reconc.acl_sync import ACLSyncService
from module_1_document_processing.del_acl_and_reconc.reconciliation_sweeper import ReconciliationSweeper

def test_deletion_handler():
    store = CanonicalStore()
    handler = DeletionHandler(store)
    
    # Record active document
    create_event = CanonicalEvent(
        event_id="evt_active_1",
        event_type=EventType.CREATE,
        source="gdrive",
        tenant_id="tenant_x",
        user_id="usr_01",
        external_id="file_del_10",
        raw_ref={},
        acl=["usr_01@example.com"],
        timestamp=datetime.now(timezone.utc),
    )
    store.record_event(create_event, status="STAGED")

    # Send DELETE event
    delete_event = CanonicalEvent(
        event_id="evt_del_1",
        event_type=EventType.DELETE,
        source="gdrive",
        tenant_id="tenant_x",
        user_id="usr_01",
        external_id="file_del_10",
        raw_ref={},
        acl=["usr_01@example.com"],
        timestamp=datetime.now(timezone.utc),
    )
    success = handler.process_deletion(delete_event)
    assert success is True
    doc = store.get_document("tenant_x:gdrive:file_del_10")
    assert doc is not None
    assert doc.status == "DELETED"

def test_acl_sync():
    store = CanonicalStore()
    acl_service = ACLSyncService(store)
    
    create_event = CanonicalEvent(
        event_id="evt_create_acl",
        event_type=EventType.CREATE,
        source="slack",
        tenant_id="tenant_x",
        user_id="usr_02",
        external_id="channel_99",
        raw_ref={},
        acl=["usr_02"],
        timestamp=datetime.now(timezone.utc),
    )
    store.record_event(create_event, status="STAGED")

    # Send ACL_CHANGE event
    acl_event = CanonicalEvent(
        event_id="evt_acl_change",
        event_type=EventType.ACL_CHANGE,
        source="slack",
        tenant_id="tenant_x",
        user_id="usr_02",
        external_id="channel_99",
        raw_ref={},
        acl=["usr_02", "usr_03", "channel:C99"],
        timestamp=datetime.now(timezone.utc),
    )
    success = acl_service.process_acl_change(acl_event)
    assert success is True
    doc = store.get_document("tenant_x:slack:channel_99")
    assert doc is not None
    assert "usr_03" in doc.acl

def test_reconciliation_sweeper():
    store = CanonicalStore()
    deletion_handler = DeletionHandler(store)
    acl_sync = ACLSyncService(store)
    sweeper = ReconciliationSweeper(store, deletion_handler, acl_sync)

    # 1. Existing record 1: Will be deleted at source
    doc1 = CanonicalEvent(
        event_id="evt_recon_1",
        event_type=EventType.CREATE,
        source="gdrive",
        tenant_id="tenant_x",
        user_id="usr_01",
        external_id="file_deleted_at_source",
        raw_ref={},
        acl=["usr_01@example.com"],
        timestamp=datetime.now(timezone.utc),
    )
    store.record_event(doc1, status="PARSED_SUCCESS")

    # 2. Existing record 2: Live ACL permissions changed at source
    doc2 = CanonicalEvent(
        event_id="evt_recon_2",
        event_type=EventType.CREATE,
        source="gdrive",
        tenant_id="tenant_x",
        user_id="usr_01",
        external_id="file_acl_changed_at_source",
        raw_ref={},
        acl=["usr_01@example.com"],
        timestamp=datetime.now(timezone.utc),
    )
    store.record_event(doc2, status="PARSED_SUCCESS")

    # Live source API response
    live_docs = [
        {"external_id": "file_acl_changed_at_source", "acl": ["usr_01@example.com", "usr_02@example.com"]},
    ]

    report = sweeper.sweep_source(tenant_id="tenant_x", source="gdrive", live_source_docs=live_docs)
    assert report.total_checked == 2
    assert report.missed_deletions_found == 1
    assert report.acl_drift_found == 1
    assert report.corrections_applied == 2

    # Verify doc1 is now DELETED
    assert store.get_document("tenant_x:gdrive:file_deleted_at_source").status == "DELETED"
    # Verify doc2 ACL is updated
    assert "usr_02@example.com" in store.get_document("tenant_x:gdrive:file_acl_changed_at_source").acl
