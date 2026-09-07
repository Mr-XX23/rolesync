import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta

# Ensure backend/data-pipeline is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent, EventType
from module_1_document_processing.composio_connector.normalizers.calendar_normalizer import normalize_calendar
from module_1_document_processing.parsing.parser_service import ParserService
from module_1_document_processing.composio_connector.calendar_store import CalendarStore
from module_1_document_processing.composio_connector.calendar_sync_manager import CalendarSyncManager
from module_1_document_processing.composio_connector.calendar_models import (
    CalendarSyncStatus,
    CalendarTriggerType,
    HistoricalSyncStatus,
    SyncPhase,
    CalendarSyncConfig,
    SyncedEventRecord,
    CalendarSyncActivity,
)
from module_2_memory_gatekeeper.category_router import CategoryRouter, DocumentCategory

async def run_calendar_tests():
    print("=== TEST 1: Google Calendar Normalization to CanonicalEvent ===")
    test_uid = uuid.uuid4().hex[:6]
    test_tenant = f"tenant_{test_uid}"
    test_user = f"usr_{test_uid}"

    now = datetime.now(timezone.utc)
    future_time = (now + timedelta(days=14)).isoformat()
    future_end = (now + timedelta(days=14, hours=1)).isoformat()

    mock_payload = {
        "metadata": {
            "user_id": test_user,
            "connected_account_id": f"conn_{test_uid}",
            "trigger_slug": "GOOGLE_CALENDAR_EVENT_UPDATED",
            "log_id": f"log_cal_{test_uid}",
        },
        "data": {
            "id": "event_meeting_001",
            "summary": "Q4 Enterprise Architecture Review",
            "description": "Deep-dive discussion on high throughput ingestion and vector embeddings.",
            "start": {"dateTime": future_time},
            "end": {"dateTime": future_end},
            "organizer": {"email": "lead-architect@enterprise.com"},
            "attendees": [
                {"email": "lead-architect@enterprise.com"},
                {"email": f"{test_user}@rolesync.ai"},
                {"email": "cto@enterprise.com"},
            ],
            "location": "Conference Room 4B / Google Meet",
            "hangoutLink": "https://meet.google.com/abc-defg-hij",
        }
    }

    canonical_event = normalize_calendar(mock_payload, tenant_id=test_tenant)
    assert isinstance(canonical_event, CanonicalEvent), "Must produce a valid CanonicalEvent"
    assert canonical_event.source == "google_calendar", "Source must be 'google_calendar'"
    assert canonical_event.external_id == "event_meeting_001", "external_id must match event id"
    assert len(canonical_event.acl) >= 2, "ACL must contain attendees and creator"
    assert canonical_event.metadata["summary"] == "Q4 Enterprise Architecture Review"
    print(" [PASS] normalize_calendar produced valid CanonicalEvent with correct ACL and metadata.")

    print("\n=== TEST 2: CategoryRouter Routing to MEETING_NOTES ===")
    parser = ParserService()
    parsed_doc = parser.parse_event(canonical_event)
    assert parsed_doc.parse_status == "SUCCESS", "Parsing should succeed"
    assert "Meeting" in parsed_doc.text_content or "Review" in parsed_doc.text_content

    router = CategoryRouter()
    cat = router.route_document(parsed_doc)
    assert cat == DocumentCategory.MEETING_NOTES, f"Calendar event must route to MEETING_NOTES, got {cat}"
    print(f" [PASS] CategoryRouter successfully classified document as '{cat.value}'.")

    print("\n=== TEST 3: CalendarStore Locking, Deduplication & Activity Logs ===")
    store = CalendarStore()
    conn = store.get_or_create_connection(tenant_id=test_tenant, user_id=test_user)
    assert conn.connection_id == f"conn_calendar_{test_tenant}_{test_user}"
    assert conn.config.categories == ["PRIMARY"], "Default categories must be ['PRIMARY']"

    # Verify Locking Lease
    lock_ok = store.acquire_lock(conn.connection_id, job_id="job_001", lease_seconds=60)
    assert lock_ok is True, "First lock acquisition must succeed"
    assert store.is_locked(conn.connection_id) is True, "Store must report connection as locked"

    # Verify Rejection on Concurrent Lock
    lock_rej = store.acquire_lock(conn.connection_id, job_id="job_002", lease_seconds=60)
    assert lock_rej is False, "Second lock acquisition with different job ID must be rejected"

    store.release_lock(conn.connection_id, job_id="job_001")
    assert store.is_locked(conn.connection_id) is False, "Store must be unlocked after release"

    # Verify Deduplication
    assert store.is_event_synced(test_tenant, conn.connection_id, "event_meeting_001") is False
    rec = SyncedEventRecord(
        doc_id=f"{test_tenant}:google_calendar:event_meeting_001",
        tenant_id=test_tenant,
        connection_id=conn.connection_id,
        event_id="event_meeting_001",
        summary="Q4 Enterprise Architecture Review",
        organizer="lead-architect@enterprise.com",
        attendees=["lead-architect@enterprise.com", f"{test_user}@rolesync.ai"],
        start_time=future_time,
        end_time=future_end,
        location="Room 4B",
        hangout_link="https://meet.google.com/abc-defg-hij",
        categories=["PRIMARY"],
        sync_status="SUCCESS",
    )
    store.record_synced_event(rec)
    assert store.is_event_synced(test_tenant, conn.connection_id, "event_meeting_001") is True, "Event must be reported as synced"
    assert store.count_synced_events(test_tenant, conn.connection_id) == 1
    print(" [PASS] CalendarStore locking, deduplication, and record tracking verified.")

    print("\n=== TEST 4: CalendarSyncManager Two-Phase Sync (Phase 1: Future 1 Year -> Phase 2: Historical 180 Days) ===")
    mgr = CalendarSyncManager(store=store)

    # Prepare Mock Events: 3 Future Events (within 1 Year) and 2 Historical Events (within 180 days)
    mock_future_events = [
        {
            "id": f"evt_fut_{i}",
            "summary": f"Upcoming Demo Call #{i}",
            "description": f"Scheduled discovery demo with enterprise client #{i}",
            "start": {"dateTime": (now + timedelta(days=10 + i * 5)).isoformat()},
            "end": {"dateTime": (now + timedelta(days=10 + i * 5, hours=1)).isoformat()},
            "organizer": {"email": f"organizer_{i}@client.com"},
            "attendees": [{"email": f"organizer_{i}@client.com"}, {"email": f"{test_user}@rolesync.ai"}],
            "calendarId": "primary",
        }
        for i in range(1, 4)
    ]

    mock_past_events = [
        {
            "id": f"evt_past_{i}",
            "summary": f"Past Project Sync #{i}",
            "description": f"Meeting notes from past sprint review #{i}",
            "start": {"dateTime": (now - timedelta(days=20 + i * 10)).isoformat()},
            "end": {"dateTime": (now - timedelta(days=20 + i * 10, hours=1)).isoformat()},
            "organizer": {"email": f"pm_{i}@internal.com"},
            "attendees": [{"email": f"pm_{i}@internal.com"}, {"email": f"{test_user}@rolesync.ai"}],
            "calendarId": "primary",
        }
        for i in range(1, 3)
    ]

    def mock_fetch_calendar_api(user_id, time_min=None, time_max=None, max_results=10, page_token=None, categories=None):
        # If time_min is around 'now' or higher, return future events
        min_dt = datetime.fromisoformat(time_min) if time_min else now
        if min_dt >= now - timedelta(minutes=5):
            return mock_future_events, None
        else:
            return mock_past_events, None

    mgr._fetch_calendar_events_api = mock_fetch_calendar_api

    # Trigger initial sync
    await mgr.start_sync_job(conn.connection_id, trigger_type=CalendarTriggerType.INITIAL_SYNC)

    # Validate results after both phases execute
    updated_conn = store.get_or_create_connection(test_tenant, test_user)
    assert updated_conn.backfill_state.is_future_complete is True, "Phase 1 (Future 1 Year) must complete"
    assert updated_conn.backfill_state.is_past_complete is True, "Phase 2 (Past 180 Days) must complete"
    assert updated_conn.backfill_state.is_backfill_complete is True, "Backfill must be completely finished"
    assert updated_conn.status == CalendarSyncStatus.UP_TO_DATE, f"Status must be 'Up to Date', got {updated_conn.status}"
    assert updated_conn.backfill_state.total_synced_so_far == 6, f"Should have synced 5 mock events + 1 previous record, got {updated_conn.backfill_state.total_synced_so_far}"
    print(f" [PASS] Two-Phase sync executed successfully: 3 future events + 2 past events -> Status: '{updated_conn.status}'.")

    print("\n=== TEST 5: Cancelled / Deleted Event Handling (EventType.DELETE) ===")
    cancelled_event_data = {
        "id": "evt_cancelled_999",
        "summary": "Cancelled Vendor Evaluation",
        "status": "cancelled",
        "start": {"dateTime": (now + timedelta(days=5)).isoformat()},
        "end": {"dateTime": (now + timedelta(days=5, hours=1)).isoformat()},
    }
    # Pre-record event as synced
    store.record_synced_event(SyncedEventRecord(
        doc_id=f"{test_tenant}:google_calendar:evt_cancelled_999",
        tenant_id=test_tenant,
        connection_id=conn.connection_id,
        event_id="evt_cancelled_999",
        summary="Cancelled Vendor Evaluation",
        organizer="vendor@eval.com",
        attendees=[],
        start_time=now.isoformat(),
        end_time=now.isoformat(),
        location="",
        hangout_link="",
        categories=["PRIMARY"],
        sync_status="SUCCESS",
    ))
    assert store.is_event_synced(test_tenant, conn.connection_id, "evt_cancelled_999") is True

    # Simulate processing cancelled event
    act = CalendarSyncActivity(
        activity_id="act_test_cancel",
        job_id="job_cancel",
        connection_id=conn.connection_id,
        tenant_id=test_tenant,
        trigger_type=CalendarTriggerType.WEBHOOK,
        status="RUNNING",
    )
    processed = await mgr._process_single_event(conn, cancelled_event_data, act)
    assert processed is True, "Cancelled event must be handled successfully"
    # Should now be deleted from synced store
    assert store.is_event_synced(test_tenant, conn.connection_id, "evt_cancelled_999") is False, "Cancelled event must be purged from store"
    print(" [PASS] Cancelled/deleted event correctly triggered cleanup.")

    print("\n=== TEST 6: All-Day Event Format Handling (start.date) ===")
    all_day_event = {
        "id": "evt_all_day_777",
        "summary": "Annual Strategy Offsite",
        "start": {"date": "2026-10-15"},
        "end": {"date": "2026-10-16"},
        "description": "Company offsite planning day.",
    }
    res_all_day = await mgr._process_single_event(conn, all_day_event, act)
    assert res_all_day is True, "All-day event with start.date must process successfully"
    assert store.is_event_synced(test_tenant, conn.connection_id, "evt_all_day_777") is True
    print(" [PASS] All-day event without explicit time parsed and indexed successfully.")

    print("\n=== TEST 7: Auto-Sync Schedule Update (2m, 30m, 1h, 6h, 24h) ===")
    res_sched = mgr.update_auto_sync_schedule(
        user_id=test_user,
        tenant_id=test_tenant,
        sync_frequency="30m",
        auto_sync_enabled=True,
    )
    assert res_sched["status"] == "success"
    assert res_sched["sync_frequency"] == "30m"
    assert res_sched["auto_sync_interval_minutes"] == 30
    assert res_sched["auto_sync_enabled"] is True
    print(" [PASS] Auto-sync schedule updated to 30m.")

    print("\n=== TEST 8: Real-Time Webhook Notification Processing ===")
    webhook_canon_event = CanonicalEvent(
        event_id=f"cal_{test_tenant}_evt_live_123",
        event_type=EventType.CREATE,
        source="google_calendar",
        tenant_id=test_tenant,
        user_id=test_user,
        external_id="evt_live_123",
        raw_ref={"event_id": "evt_live_123"},
        acl=[test_user],
        timestamp=now,
        metadata={
            "summary": "Urgent Prospect Negotiation Call",
            "start_time": (now + timedelta(hours=2)).isoformat(),
            "end_time": (now + timedelta(hours=3)).isoformat(),
            "description": "Live incoming webhook meeting notes.",
        },
    )
    # Enable webhooks in config
    conn.config.webhook_enabled = True
    store.update_connection(conn)

    wh_res = await mgr.process_webhook_event(webhook_canon_event)
    assert wh_res["status"] == "processed"
    assert store.is_event_synced(test_tenant, conn.connection_id, "evt_live_123") is True
    print(" [PASS] Real-time calendar webhook event processed and indexed.")

    print("\n=== TEST 9: Cascade Data Purge & Watermark Reset ===")
    purge_res = await mgr.purge_all_connector_data(user_id=test_user, tenant_id=test_tenant)
    assert purge_res["status"] == "success"
    assert purge_res["purged_metrics"]["synced_events_deleted"] > 0
    # Check count after purge
    assert store.count_synced_events(test_tenant, conn.connection_id) == 0, "All events must be purged"
    reloaded_conn = store.get_or_create_connection(test_tenant, test_user)
    assert reloaded_conn.backfill_state.total_synced_so_far == 0, "Watermarks must be reset"
    assert reloaded_conn.backfill_state.is_backfill_complete is False
    print(" [PASS] Cascade data purge successfully wiped MongoDB/memory records and reset watermarks.")

    print("\n ALL GOOGLE CALENDAR TESTS PASSED SUCCESSFULLY! ")

if __name__ == "__main__":
    asyncio.run(run_calendar_tests())
