import asyncio
from datetime import datetime, timezone
from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent, EventType
from module_1_document_processing.security.security_scanner import SecurityScanner
from module_1_document_processing.pipeline.canonical_store import CanonicalStore
from module_1_document_processing.pipeline.queue_worker import QueueWorker

def test_security_scanner_clean_event():
    scanner = SecurityScanner()
    event = CanonicalEvent(
        event_id="evt_sec_01",
        event_type=EventType.CREATE,
        source="gdrive",
        tenant_id="tenant_100",
        user_id="usr_001",
        external_id="file_01",
        raw_ref={},
        acl=["usr_001@example.com"],
        timestamp=datetime.now(timezone.utc),
        metadata={"title": "Clean Document.pdf\x00"},
    )
    res = scanner.scan_and_sanitize_event(event)
    assert res.is_safe is True
    assert event.metadata["title"] == "Clean Document.pdf"

def test_security_scanner_script_injection():
    scanner = SecurityScanner()
    event = CanonicalEvent(
        event_id="evt_sec_02",
        event_type=EventType.CREATE,
        source="slack",
        tenant_id="tenant_100",
        user_id="usr_002",
        external_id="msg_02",
        raw_ref={},
        acl=["usr_002"],
        timestamp=datetime.now(timezone.utc),
        metadata={"text": "<script>alert('malicious')</script>"},
    )
    res = scanner.scan_and_sanitize_event(event)
    assert res.is_safe is False
    assert "script injection" in res.reason.lower()

def test_canonical_store():
    store = CanonicalStore()
    event = CanonicalEvent(
        event_id="evt_store_01",
        event_type=EventType.UPDATE,
        source="notion",
        tenant_id="tenant_200",
        user_id="usr_003",
        external_id="page_999",
        raw_ref={},
        acl=["usr_003"],
        timestamp=datetime.now(timezone.utc),
        metadata={"title": "Meeting Notes"},
    )
    record = store.record_event(event, status="STAGED")
    assert record.doc_id == "tenant_200:notion:page_999"
    assert record.status == "STAGED"
    
    # Test ACL snapshot update
    updated = store.update_acl("tenant_200:notion:page_999", ["usr_003", "usr_004"])
    assert updated is True
    doc = store.get_document("tenant_200:notion:page_999")
    assert doc is not None
    assert "usr_004" in doc.acl

def test_queue_worker_async():
    async def run_worker_test():
        scanner = SecurityScanner()
        store = CanonicalStore()
        worker = QueueWorker(scanner=scanner, store=store)
        await worker.start()

        event = CanonicalEvent(
            event_id="evt_qw_01",
            event_type=EventType.CREATE,
            source="gmail",
            tenant_id="tenant_300",
            user_id="usr_005",
            external_id="msg_qw_01",
            raw_ref={},
            acl=["usr_005@example.com"],
            timestamp=datetime.now(timezone.utc),
            metadata={"subject": "Async Test"},
        )
        await worker.enqueue(event)
        await asyncio.sleep(0.2)  # Give worker loop time to process

        doc = store.get_document("tenant_300:gmail:msg_qw_01")
        assert doc is not None
        assert doc.status in ("STAGED", "PARSED_SUCCESS", "GATEKEEPER_ACCEPTED", "VECTOR_STORE_INDEXED")

        await worker.stop()

    asyncio.run(run_worker_test())
