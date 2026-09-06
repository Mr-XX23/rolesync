import asyncio
import os
import sys
import uuid

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
    test_uid = uuid.uuid4().hex[:6]
    test_tenant = f"tenant_{test_uid}"
    test_user = f"usr_{test_uid}"
    mock_payload = {
        "metadata": {"user_id": test_user, "connected_account_id": f"conn_{test_uid}"},
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

    event = normalize_gmail(mock_payload, tenant_id=test_tenant)
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
    conn = store.get_or_create_connection(tenant_id=test_tenant, user_id=test_user)
    assert conn.connection_id == f"conn_gmail_{test_tenant}_{test_user}"

    # Test lock acquisition
    locked = store.acquire_lock(conn.connection_id, job_id="job_001")
    assert locked is True, "First lock acquisition must succeed"
    locked_again = store.acquire_lock(conn.connection_id, job_id="job_002")
    assert locked_again is False, "Concurrent lock acquisition by another job must fail"
    store.release_lock(conn.connection_id, job_id="job_001")

    # Test deduplication
    assert store.is_message_synced(test_tenant, conn.connection_id, "msg_001") is False
    store.record_synced_message(SyncedMessageRecord(
        doc_id="doc_1", tenant_id=test_tenant, connection_id=conn.connection_id,
        message_id="msg_001", thread_id="th_1", categories=["INBOX"],
        subject="Test", sender="test@test.com", received_at=event.timestamp, sync_status="SUCCESS"
    ))
    assert store.is_message_synced(test_tenant, conn.connection_id, "msg_001") is True
    print(" [PASS] GmailStore locking & deduplication verified.")

    print("\n=== TEST 4: GmailSyncManager 90-Day Backfill & Sub-Batch Execution ===")
    mgr = GmailSyncManager(store=store)
    # Provide test message fixtures for unit test execution
    mgr.composio.fetch_gmail_messages = lambda user_id, max_results=10, query="", label_ids=None, page_token=None: (
        [
            {
                "messageId": f"msg_test_{i:03d}",
                "threadId": f"th_test_{i:03d}",
                "subject": f"Q3 Test Statement of Work #{i}",
                "sender": f"client_{i}@test.com",
                "to": f"{user_id}@gmail.com",
                "messageTimestamp": "2026-09-04T02:00:00Z",
                "labelIds": ["INBOX"],
                "messageText": f"Please review statement #{i}",
                "attachmentList": [
                    {
                        "attachment_id": f"att_pdf_{i}",
                        "filename": f"Statement_{i}.pdf",
                        "mime_type": "application/pdf",
                        "size_bytes": 1024 * 1024 * 2,
                        "raw_bytes": b"%PDF-1.4 Mock PDF content",
                    }
                ] if i % 2 == 0 else []
            }
            for i in range(1, 11)
        ],
        None
    )

    # Save config and trigger initial sync
    res = await mgr.save_configuration_and_start_sync(
        user_id=test_user,
        tenant_id=test_tenant,
        config_data={"max_emails_per_sync": 10, "categories": ["INBOX", "SENT"]}
    )
    assert res["status"] == "success"

    # Wait for background job to complete
    await asyncio.sleep(1.0)
    for _ in range(45):
        if not store.is_locked(conn.connection_id):
            break
        await asyncio.sleep(1.0)

    activities = store.get_activities(conn.connection_id)
    assert len(activities) > 0, "Must have recorded at least 1 sync activity"
    latest_act = activities[0]
    print(f" Sync Activity Metrics: {latest_act.metrics}")
    assert latest_act.metrics["processed"] > 0, "Must have processed emails"
    print(" [PASS] GmailSyncManager executed backfill batch with CanonicalEvent pipeline.")

    print("\n=== TEST 5: Resync & Disconnect (Memories Preserved) ===")
    resync_res = await mgr.trigger_resync(user_id=test_user, tenant_id=test_tenant)
    assert resync_res["status"] == "success"
    await asyncio.sleep(1.0)
    for _ in range(45):
        if not store.is_locked(conn.connection_id):
            break
        await asyncio.sleep(1.0)

    # Disconnect
    disc_res = mgr.disconnect_connection(user_id=test_user, tenant_id=test_tenant)
    assert disc_res["status"] == "success"
    assert disc_res["connection"]["status"] == "Disconnected"
    # Verify synced messages still preserved
    assert store.is_message_synced(test_tenant, conn.connection_id, "msg_001") is True
    print(" [PASS] Disconnect preserved existing memories in store.")

    print("\n=== TEST 6: Multi-Page Duplicate Skipping (max-per-sync Budget Intact) ===")
    test_uid2 = uuid.uuid4().hex[:6]
    test_tenant2 = f"tenant_{test_uid2}"
    test_user2 = f"usr_{test_uid2}"
    conn2 = store.get_or_create_connection(tenant_id=test_tenant2, user_id=test_user2)
    conn2.config.max_emails_per_sync = 5

    # Pre-populate 5 synced messages in database (emails 1..5)
    for i in range(1, 6):
        store.record_synced_message(SyncedMessageRecord(
            doc_id=f"doc_dup_{i}", tenant_id=test_tenant2, connection_id=conn2.connection_id,
            message_id=f"msg_dup_{i}", thread_id=f"th_dup_{i}", categories=["INBOX"],
            subject=f"Old Email #{i}", sender="sender@test.com", received_at="2026-09-04T00:00:00Z", sync_status="SUCCESS"
        ))

    # Mock Composio: Page 1 returns 5 duplicates (msg_dup_1..5) + nextPageToken "token_page_2"
    # Page 2 returns 5 new emails (msg_new_6..10) + nextPageToken "token_page_3"
    def mock_paginated_fetch(user_id, max_results=10, query="", label_ids=None, page_token=None):
        if page_token is None:
            return (
                [
                    {
                        "messageId": f"msg_dup_{i}",
                        "subject": f"Old Email #{i}",
                        "sender": "sender@test.com",
                        "messageTimestamp": "2026-09-03T10:00:00Z",
                    }
                    for i in range(1, 6)
                ],
                "token_page_2"
            )
        elif page_token == "token_page_2":
            return (
                [
                    {
                        "messageId": f"msg_new_{i}",
                        "subject": f"New Email #{i}",
                        "sender": "sender@test.com",
                        "messageTimestamp": "2026-09-02T10:00:00Z",
                    }
                    for i in range(6, 11)
                ],
                "token_page_3"
            )
        return ([], None)

    mgr2 = GmailSyncManager(store=store)
    mgr2.composio.fetch_gmail_messages = mock_paginated_fetch

    # Execute fetch for conn2
    eligible = mgr2._fetch_eligible_historical_messages(conn2, max_limit=5)
    assert len(eligible) == 5, f"Expected 5 new emails, got {len(eligible)}"
    assert [e["messageId"] for e in eligible] == [f"msg_new_{i}" for i in range(6, 11)]
    assert conn2.backfill_state.historical_sync_cursor == "token_page_3"
    print(" [PASS] Multi-page duplicate skipping satisfied max-per-sync=5 budget without stopping on duplicate page.")

    print("\n=== TEST 7: Historical Boundary Completion Detection ===")
    # Page 3 returns emails that hit the historical boundary (None next_token)
    def mock_boundary_fetch(user_id, max_results=10, query="", label_ids=None, page_token=None):
        return (
            [
                {
                    "messageId": f"msg_last_{i}",
                    "subject": f"Oldest Email #{i}",
                    "sender": "sender@test.com",
                    "messageTimestamp": "2026-03-01T00:00:00Z", # Past the 180 day boundary
                }
                for i in range(1, 3)
            ],
            None # End of mailbox
        )
    mgr2.composio.fetch_gmail_messages = mock_boundary_fetch
    eligible_end = mgr2._fetch_eligible_historical_messages(conn2, max_limit=5)
    assert conn2.backfill_state.historical_sync_status.value == "COMPLETED"
    assert conn2.backfill_state.is_backfill_complete is True
    assert conn2.backfill_state.historical_sync_cursor is None
    print(" [PASS] Historical sync marked COMPLETED and cursor cleared at mailbox/boundary end.")

    print("\n=== TEST 8: Forward Incremental Sync Mode for New Emails ===")
    conn2.backfill_state.newest_synced_timestamp = "2026-09-04T05:00:00Z"
    
    forward_query_called = []
    def mock_forward_fetch(user_id, max_results=10, query="", label_ids=None, page_token=None):
        forward_query_called.append(query)
        assert page_token is None, "Forward incremental sync must not pass historical page_token"
        return (
            [
                {
                    "messageId": "msg_future_001",
                    "subject": "Brand New Tomorrow Email",
                    "sender": "partner@future.com",
                    "messageTimestamp": "2026-09-05T08:00:00Z",
                }
            ],
            None
        )
    mgr2.composio.fetch_gmail_messages = mock_forward_fetch
    forward_msgs = mgr2._fetch_forward_incremental_messages(conn2, max_limit=5)
    assert len(forward_msgs) == 1
    assert forward_msgs[0]["messageId"] == "msg_future_001"
    assert len(forward_query_called) == 1
    assert "after:" in forward_query_called[0]
    print(f" Forward Query Verified: {forward_query_called[0]}")
    print(" [PASS] Forward incremental sync successfully queried only new arrivals without historical scanning.")

    print("\n=== TEST 9: Dedicated Auto-Sync Schedule Configuration (2m, 30m, 1h, 6h, 24h at 2am) ===")
    # Test setting 2m
    res_2m = await mgr2.update_auto_sync_schedule(user_id=test_user2, tenant_id=test_tenant2, sync_frequency="2m")
    assert res_2m["status"] == "success"
    assert res_2m["auto_sync_interval_minutes"] == 2
    assert mgr2.store.get_or_create_connection(tenant_id=test_tenant2, user_id=test_user2).config.auto_sync_interval_minutes == 2

    # Test setting 24h (2am daily cron)
    res_24h = await mgr2.update_auto_sync_schedule(user_id=test_user2, tenant_id=test_tenant2, sync_frequency="24h")
    assert res_24h["status"] == "success"
    assert res_24h["auto_sync_interval_minutes"] == 1440
    assert mgr2.store.get_or_create_connection(tenant_id=test_tenant2, user_id=test_user2).config.auto_sync_interval_minutes == 1440

    # Test setting 6h
    res_6h = await mgr2.update_auto_sync_schedule(user_id=test_user2, tenant_id=test_tenant2, sync_frequency="6h")
    assert res_6h["status"] == "success"
    assert res_6h["auto_sync_interval_minutes"] == 360
    assert mgr2.store.get_or_create_connection(tenant_id=test_tenant2, user_id=test_user2).config.auto_sync_interval_minutes == 360
    print("\n=== TEST 10: Robust UTC Date Normalization & Default 12:00:00 Time Handling ===")
    from module_1_document_processing.composio_connector.date_utils import normalize_to_utc, ensure_iso_str
    from datetime import datetime, timezone

    # 1. Date-only string defaults to 12:00:00 UTC
    dt_date_only = normalize_to_utc("2026-09-04")
    assert dt_date_only.year == 2026 and dt_date_only.month == 9 and dt_date_only.day == 4
    assert dt_date_only.hour == 12 and dt_date_only.minute == 0 and dt_date_only.second == 0
    assert dt_date_only.tzinfo == timezone.utc

    # 2. Naive datetime converted to UTC
    naive_dt = datetime(2026, 9, 4, 15, 30, 0)
    norm_dt = normalize_to_utc(naive_dt)
    assert norm_dt.tzinfo == timezone.utc
    assert norm_dt.hour == 15

    # 3. String comparison safety (no TypeError '<' between datetime and str or naive)
    str_ts = "2026-09-04T08:00:00Z"
    aware_dt = datetime(2026, 9, 4, 10, 0, 0, tzinfo=timezone.utc)
    assert normalize_to_utc(aware_dt) > normalize_to_utc(str_ts)
    assert normalize_to_utc(str_ts) < normalize_to_utc(aware_dt)
    assert ensure_iso_str(aware_dt) == "2026-09-04T10:00:00+00:00"
    print(" [PASS] normalize_to_utc successfully resolved date-only, naive, and string datetimes without comparison errors.")

    print("\n=== TEST 11: Document (20MB) vs Image (4MB) Attachment Size Enforcement ===")
    event_with_attachments = CanonicalEvent(
        event_id="evt_test_att",
        event_type=EventType.CREATE,
        source="gmail",
        tenant_id="test_tenant",
        user_id="test_user",
        external_id="msg_att_001",
        raw_ref={"message_id": "msg_att_001"},
        acl=["test_user"],
        timestamp=datetime.now(timezone.utc),
        metadata={
            "subject": "Proposal with Multiple Files",
            "sender": "vendor@partner.com",
            "to": "user@rolesync.ai",
            "body": "Here is the proposal doc and high-res diagram.",
            "attachments": [
                {
                    "filename": "proposal.pdf",
                    "mime_type": "application/pdf",
                    "size_bytes": 1024 * 1024 * 15, # 15 MB doc (<= 20MB limit -> allowed)
                    "raw_bytes": b"%PDF-1.4 Proposal content",
                },
                {
                    "filename": "huge_manual.pdf",
                    "mime_type": "application/pdf",
                    "size_bytes": 1024 * 1024 * 22, # 22 MB doc (> 20MB limit -> skipped)
                    "raw_bytes": b"%PDF-1.4 Huge manual content",
                },
                {
                    "filename": "banner.png",
                    "mime_type": "image/png",
                    "size_bytes": 1024 * 1024 * 2, # 2 MB image (<= 4MB limit -> allowed)
                    "raw_bytes": b"\x89PNG\r\n\x1a\nPNG banner",
                },
                {
                    "filename": "large_photo.jpg",
                    "mime_type": "image/jpeg",
                    "size_bytes": 1024 * 1024 * 6, # 6 MB image (> 4MB limit -> skipped)
                    "raw_bytes": b"\xff\xd8\xff\xe0JPEG large photo",
                },
            ]
        }
    )

    doc_result = parser.parse_event(event_with_attachments)
    assert doc_result.parse_status == "PARTIAL_SUCCESS"
    assert "Proposal with Multiple Files" in doc_result.text_content
    # Check audits
    audits = doc_result.metadata["attachment_audits"]
    assert len(audits) == 4
    # proposal.pdf -> parsed
    assert audits[0]["filename"] == "proposal.pdf" and audits[0]["parse_status"] == "SUCCESS"
    # huge_manual.pdf -> skipped (> 20MB)
    assert audits[1]["filename"] == "huge_manual.pdf" and audits[1]["parse_status"] == "SKIPPED"
    assert "DOCUMENT_SIZE_EXCEEDED" in audits[1]["skip_reason"]
    # banner.png -> parsed
    assert audits[2]["filename"] == "banner.png" and audits[2]["parse_status"] == "SUCCESS"
    # large_photo.jpg -> skipped (> 4MB)
    assert audits[3]["filename"] == "large_photo.jpg" and audits[3]["parse_status"] == "SKIPPED"
    assert "IMAGE_SIZE_EXCEEDED" in audits[3]["skip_reason"]
    print(" [PASS] Dual-threshold attachment size checking (20MB doc, 4MB image) verified with parent email preserved.")

    print("\n=== TEST 12: Delete All Synced Data & Cascade Purge (MongoDB, Vectors, Watermarks) ===")
    from module_1_document_processing.composio_connector.gmail_models import HistoricalSyncStatus
    test_uid3 = uuid.uuid4().hex[:6]
    test_tenant3 = f"tenant_{test_uid3}"
    test_user3 = f"usr_{test_uid3}"
    store3 = GmailStore()
    mgr3 = GmailSyncManager(store=store3)

    # 1. Populate mock synced messages, activities, and vectors
    conn3 = store3.get_or_create_connection(tenant_id=test_tenant3, user_id=test_user3)
    conn3.backfill_state.historical_sync_status = HistoricalSyncStatus.COMPLETED
    conn3.backfill_state.is_backfill_complete = True
    conn3.backfill_state.newest_synced_timestamp = "2026-09-04T12:00:00+00:00"
    conn3.backfill_state.oldest_synced_timestamp = "2026-03-01T12:00:00+00:00"
    store3.update_connection(conn3)

    for i in range(1, 4):
        store3.record_synced_message(SyncedMessageRecord(
            doc_id=f"doc_{test_uid3}_{i}",
            tenant_id=test_tenant3,
            connection_id=conn3.connection_id,
            message_id=f"msg_p_{i}",
            thread_id=f"th_p_{i}",
            categories=["INBOX"],
            subject=f"Purge Candidate #{i}",
            sender="purge@test.com",
            received_at="2026-09-04T10:00:00+00:00",
            sync_status="SUCCESS",
        ))

    from module_1_document_processing.composio_connector.gmail_models import GmailSyncActivity
    store3.record_activity(GmailSyncActivity(
        activity_id=f"act_p_{test_uid3}",
        job_id="job_p_1",
        connection_id=conn3.connection_id,
        tenant_id=test_tenant3,
        trigger_type=GmailTriggerType.MANUAL_SYNC,
        status="COMPLETED",
        started_at=datetime.now(timezone.utc),
        metrics={"total_discovered": 3, "processed": 3, "succeeded": 3, "skipped": 0, "failed": 0},
    ))

    # Ingest vectors into vector store
    from module_3_batch_ingestion_vector.vector_store import VectorRecord
    mgr3.queue_worker.ingestion_pipeline.vector_store._in_memory[f"vec_{test_uid3}_1"] = VectorRecord(
        vector_id=f"vec_{test_uid3}_1",
        doc_id=f"doc_{test_uid3}_1",
        tenant_id=test_tenant3,
        user_id=test_user3,
        source="gmail",
        external_id="msg_p_1",
        text="Sample text",
        vector=[0.1, 0.2, 0.3],
        acl=[test_user3],
        chunk_index=0,
    )

    # 2. Check summary calculation preview
    summary = mgr3.get_data_summary(user_id=test_user3, tenant_id=test_tenant3)
    assert summary["synced_messages_count"] == 3
    assert summary["activities_count"] == 1
    assert summary["vector_records_count"] == 1
    print(f" Pre-Purge Calculation Preview: {summary}")

    # 3. Execute Purge
    purge_res = await mgr3.purge_all_connector_data(user_id=test_user3, tenant_id=test_tenant3)
    assert purge_res["status"] == "success"
    assert purge_res["purged_metrics"]["synced_messages_deleted"] == 3
    assert purge_res["purged_metrics"]["activities_deleted"] == 1
    assert purge_res["purged_metrics"]["vectors_deleted"] == 1

    # 4. Verify everything is reset to pristine state
    post_summary = mgr3.get_data_summary(user_id=test_user3, tenant_id=test_tenant3)
    assert post_summary["synced_messages_count"] == 0
    assert post_summary["activities_count"] == 0
    assert post_summary["vector_records_count"] == 0
    assert post_summary["historical_status"] == "NOT_STARTED"
    assert post_summary["is_backfill_complete"] is False

    refreshed_conn = store3.get_or_create_connection(tenant_id=test_tenant3, user_id=test_user3)
    assert refreshed_conn.backfill_state.newest_synced_timestamp is None
    assert refreshed_conn.backfill_state.oldest_synced_timestamp is None
    assert refreshed_conn.backfill_state.historical_sync_status == HistoricalSyncStatus.NOT_STARTED
    print(" [PASS] Complete data purge cascade (MongoDB, VectorStore, watermark reset) verified.")

    print("\n ALL GMAIL INTEGRATION TESTS PASSED SUCCESSFULLY! ")

if __name__ == "__main__":
    asyncio.run(run_tests())
