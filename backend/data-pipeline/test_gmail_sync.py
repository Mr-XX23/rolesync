import asyncio
import os
import sys

# Ensure backend/data-pipeline is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent, EventType
from module_1_document_processing.composio_connector.normalizers.gmail_normalizer import normalize_gmail
from module_1_document_processing.parsing.parser_service import ParserService
from module_1_document_processing.composio_connector.gmail_store import GmailStore
from module_1_document_processing.composio_connector.gmail_sync_manager import GmailSyncManager
from module_1_document_processing.composio_connector.gmail_models import (
    GmailSyncStatus,
    GmailTriggerType,
    SyncedMessageRecord,
)

async def run_tests():
    print("=== TEST 1: Gmail Normalization to CanonicalEvent ===")
    mock_payload = {
        "metadata": {"user_id": "usr_test", "connected_account_id": "conn_123"},
        "data": {
            "message_id": "msg_001",
            "thread_id": "th_001",
            "subject": "Q3 Contract Review",
            "sender": "partner@enterprise.com",
            "to": "user@rolesync.ai",
            "body": "Please review the attached contract document and large diagnostic dump.",
            "label_ids": ["INBOX", "IMPORTANT"],
            "attachments": [
                {
                    "filename": "Agreement.pdf",
                    "mime_type": "application/pdf",
                    "size_bytes": 1024 * 1024 * 2, # 2MB (valid)
                    "raw_bytes": b"%PDF-1.4 Agreement content",
                },
                {
                    "filename": "Large_Dump.zip",
                    "mime_type": "application/zip",
                    "size_bytes": 1024 * 1024 * 35, # 35MB (oversized >25MB)
                    "raw_bytes": b"PK\x03\x04Large archive data",
                }
            ]
        }
    }

    event = normalize_gmail(mock_payload, tenant_id="tenant_test")
    assert isinstance(event, CanonicalEvent), "Event must be an instance of CanonicalEvent"
    assert event.source == "gmail", "Event source must be 'gmail'"
    assert event.external_id == "msg_001", "Event external_id must match message_id"
    assert len(event.metadata["attachments"]) == 2, "Must normalize 2 attachments"
    print(" [PASS] normalize_gmail produced valid CanonicalEvent.")

    print("\n=== TEST 2: Combined Email & Attachment Parsing with 25MB Isolation ===")
    parser = ParserService()
    parsed_doc = parser.parse_event(event)
    assert parsed_doc.parse_status in ("SUCCESS", "PARTIAL_SUCCESS"), f"Expected SUCCESS or PARTIAL_SUCCESS, got {parsed_doc.parse_status}"
    assert "# Email: Q3 Contract Review" in parsed_doc.text_content, "Must contain email subject header"
    assert "Please review the attached contract" in parsed_doc.text_content, "Must contain email body text"
    assert "Agreement.pdf" in parsed_doc.text_content, "Must contain parsed attachment section"
    assert "Skipped Attachment: Large_Dump.zip" in parsed_doc.text_content, "Must contain skipped notice for oversized zip"
    print(" [PASS] ParserService combined body + valid attachment and skipped >25MB file without failing email.")

    print("\n=== TEST 3: GmailStore Locking, Deduplication & Activities ===")
    store = GmailStore()
    conn = store.get_or_create_connection(tenant_id="tenant_test", user_id="usr_test")
    assert conn.connection_id == "conn_gmail_tenant_test_usr_test"

    # Test lock acquisition
    locked = store.acquire_lock(conn.connection_id, job_id="job_001")
    assert locked is True, "First lock acquisition must succeed"
    locked_again = store.acquire_lock(conn.connection_id, job_id="job_002")
    assert locked_again is False, "Concurrent lock acquisition by another job must fail"
    store.release_lock(conn.connection_id, job_id="job_001")

    # Test deduplication
    assert store.is_message_synced("tenant_test", conn.connection_id, "msg_001") is False
    store.record_synced_message(SyncedMessageRecord(
        doc_id="doc_1", tenant_id="tenant_test", connection_id=conn.connection_id,
        message_id="msg_001", thread_id="th_1", categories=["INBOX"],
        subject="Test", sender="test@test.com", received_at=event.timestamp, sync_status="SUCCESS"
    ))
    assert store.is_message_synced("tenant_test", conn.connection_id, "msg_001") is True
    print(" [PASS] GmailStore locking & deduplication verified.")

    print("\n=== TEST 4: GmailSyncManager 90-Day Backfill & Sub-Batch Execution ===")
    mgr = GmailSyncManager(store=store)
    # Save config and trigger initial sync
    res = await mgr.save_configuration_and_start_sync(
        user_id="usr_test",
        tenant_id="tenant_test",
        config_data={"max_emails_per_sync": 10, "categories": ["INBOX", "SENT"]}
    )
    assert res["status"] == "success"

    # Wait for background job to complete
    await asyncio.sleep(2.0)

    activities = store.get_activities(conn.connection_id)
    assert len(activities) > 0, "Must have recorded at least 1 sync activity"
    latest_act = activities[0]
    print(f" Sync Activity Metrics: {latest_act.metrics}")
    assert latest_act.metrics["processed"] > 0, "Must have processed emails"
    print(" [PASS] GmailSyncManager executed backfill batch with CanonicalEvent pipeline.")

    print("\n=== TEST 5: Resync & Disconnect (Memories Preserved) ===")
    resync_res = await mgr.trigger_resync(user_id="usr_test", tenant_id="tenant_test")
    assert resync_res["status"] == "success"
    await asyncio.sleep(1.0)

    # Disconnect
    disc_res = mgr.disconnect_connection(user_id="usr_test", tenant_id="tenant_test")
    assert disc_res["status"] == "success"
    assert disc_res["connection"]["status"] == "Disconnected"
    # Verify synced messages still preserved
    assert store.is_message_synced("tenant_test", conn.connection_id, "msg_001") is True
    print(" [PASS] Disconnect preserved existing memories in store.")

    print("\n ALL GMAIL INTEGRATION TESTS PASSED SUCCESSFULLY! ")

if __name__ == "__main__":
    asyncio.run(run_tests())
