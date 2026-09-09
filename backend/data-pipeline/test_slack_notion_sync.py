import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

# Ensure backend/data-pipeline is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent, EventType
from module_1_document_processing.composio_connector.normalizers.slack_normalizer import normalize_slack
from module_1_document_processing.composio_connector.normalizers.notion_normalizer import normalize_notion
from module_1_document_processing.composio_connector.slack_models import (
    SlackSyncStatus,
    SlackTriggerType,
    SlackSyncConfig,
    SyncedSlackMessageRecord,
)
from module_1_document_processing.composio_connector.slack_store import SlackStore
from module_1_document_processing.composio_connector.slack_sync_manager import SlackSyncManager

from module_1_document_processing.composio_connector.notion_models import (
    NotionSyncStatus,
    NotionTriggerType,
    NotionSyncConfig,
    SyncedNotionRecord,
)
from module_1_document_processing.composio_connector.notion_store import NotionStore
from module_1_document_processing.composio_connector.notion_sync_manager import NotionSyncManager

async def run_tests():
    print("=== TEST 1: Slack Normalization (DMs, Group Chats, Channels, Threads) ===")
    test_uid = uuid.uuid4().hex[:6]
    test_tenant = f"tenant_{test_uid}"
    test_user = f"usr_{test_uid}"

    # 1. Direct Message (DM)
    dm_payload = {
        "metadata": {"user_id": test_user, "trigger_slug": "SLACKBOT_DIRECT_MESSAGE_RECEIVED"},
        "data": {
            "channel": "D12345678",
            "user": "U_BOB",
            "user_name": "bob_client",
            "ts": "1710000000.001",
            "text": "Hi, can you send over the custom quote?",
            "recipients": [test_user, "U_BOB"],
            "is_im": True,
        }
    }
    event_dm = normalize_slack(dm_payload, tenant_id=test_tenant)
    assert isinstance(event_dm, CanonicalEvent)
    assert event_dm.source == "slack"
    assert event_dm.metadata["message_type"] == "im"
    assert "U_BOB" in event_dm.acl and test_user in event_dm.acl
    assert "custom quote" in event_dm.metadata["text"]
    print(" [PASS] Slack DM normalized with user ACLs and message type 'im'.")

    # 2. Multi-Person Group Chat (MPIM)
    mpim_payload = {
        "metadata": {"user_id": test_user, "trigger_slug": "SLACKBOT_GROUP_MESSAGE_RECEIVED"},
        "data": {
            "channel": "G87654321",
            "user": "U_CHARLIE",
            "user_name": "charlie_sales",
            "ts": "1710000010.002",
            "text": "Meeting moved to 3 PM UTC.",
            "members": [test_user, "U_CHARLIE", "U_DAVE"],
            "is_mpim": True,
        }
    }
    event_mpim = normalize_slack(mpim_payload, tenant_id=test_tenant)
    assert event_mpim.metadata["message_type"] == "mpim"
    assert "U_DAVE" in event_mpim.acl
    print(" [PASS] Slack Group Message (MPIM) normalized with multi-user ACLs.")

    # 3. Public Channel with Thread Reply & Attachment
    chan_payload = {
        "metadata": {"user_id": test_user, "trigger_slug": "SLACK_NEW_MESSAGE"},
        "data": {
            "channel": "C01234567",
            "channel_name": "enterprise-deals",
            "user": "U_ALICE",
            "user_name": "alice_lead",
            "ts": "1710000020.003",
            "thread_ts": "1710000000.000",
            "text": "Here is the revised statement of work.",
            "files": [{"id": "F_999", "name": "SOW_v2.pdf", "mimetype": "application/pdf", "size": 15000}],
        }
    }
    event_chan = normalize_slack(chan_payload, tenant_id=test_tenant)
    assert event_chan.metadata["message_type"] == "public_channel"
    assert event_chan.metadata["thread_ts"] == "1710000000.000"
    assert len(event_chan.metadata["files"]) == 1
    assert "channel:C01234567" in event_chan.acl
    print(" [PASS] Slack Public Channel with Thread Reply and File attachments normalized.")

    print("\n=== TEST 2: Notion Normalization (Pages, Databases, Blocks, Comments) ===")
    # 1. Notion Page
    page_payload = {
        "metadata": {"user_id": test_user, "trigger_slug": "NOTION_PAGE_CREATED_TRIGGER"},
        "data": {
            "id": "page_001",
            "object": "page",
            "url": "https://notion.so/page_001",
            "properties": {
                "title": {"type": "title", "title": [{"plain_text": "Engineering Design Doc"}]},
                "Status": {"type": "status", "status": {"name": "In Review"}},
            },
            "markdown": "This document outlines the architecture for Notion integration.",
            "last_edited_time": "2026-09-08T00:00:00Z",
        }
    }
    event_page = normalize_notion(page_payload, tenant_id=test_tenant)
    assert isinstance(event_page, CanonicalEvent)
    assert event_page.source == "notion"
    assert event_page.metadata["title"] == "Engineering Design Doc"
    assert event_page.metadata["object_type"] == "page"
    assert "In Review" in event_page.metadata["text"]
    print(" [PASS] Notion Page normalized with properties and markdown content.")

    # 2. Notion Database
    db_payload = {
        "metadata": {"user_id": test_user, "trigger_slug": "NOTION_DATABASE_UPDATED_TRIGGER"},
        "data": {
            "id": "db_001",
            "object": "database",
            "title": [{"plain_text": "Sprint Backlog & Tasks"}],
            "url": "https://notion.so/db_001",
            "last_edited_time": "2026-09-08T00:05:00Z",
        }
    }
    event_db = normalize_notion(db_payload, tenant_id=test_tenant)
    assert event_db.metadata["title"] == "Sprint Backlog & Tasks"
    assert event_db.metadata["object_type"] == "database"
    print(" [PASS] Notion Database normalized.")

    # 3. Notion Comment
    comment_payload = {
        "metadata": {"user_id": test_user, "trigger_slug": "NOTION_COMMENT_CREATED_TRIGGER"},
        "data": {
            "id": "comment_001",
            "object": "comment",
            "rich_text": [{"plain_text": "Please make sure rate limits are set to default 15, max 30."}],
            "last_edited_time": "2026-09-08T00:06:00Z",
        }
    }
    event_comment = normalize_notion(comment_payload, tenant_id=test_tenant)
    assert event_comment.metadata["object_type"] == "comment"
    assert "default 15, max 30" in event_comment.metadata["text"]
    print(" [PASS] Notion Comment discussion normalized.")

    print("\n=== TEST 3: Connection Isolation & Atomic Locking ===")
    slack_store = SlackStore()
    notion_store = NotionStore()

    slack_conn = slack_store.get_or_create_connection(tenant_id=test_tenant, user_id=test_user)
    notion_conn = notion_store.get_or_create_connection(tenant_id=test_tenant, user_id=test_user)

    assert slack_conn.connection_id == f"conn_slack_{test_tenant}_{test_user}"
    assert notion_conn.connection_id == f"conn_notion_{test_tenant}_{test_user}"

    # Lock Slack connection
    slack_locked = slack_store.acquire_lock(slack_conn.connection_id, job_id="slack_job_1")
    assert slack_locked is True, "Slack lock must succeed"
    assert slack_store.is_locked(slack_conn.connection_id) is True

    # Verify Notion is completely unaffected by Slack lock
    assert notion_store.is_locked(notion_conn.connection_id) is False, "Notion must not be locked when Slack is locked!"
    notion_locked = notion_store.acquire_lock(notion_conn.connection_id, job_id="notion_job_1")
    assert notion_locked is True, "Notion lock must succeed independently!"
    assert notion_store.is_locked(notion_conn.connection_id) is True

    # Release locks independently
    slack_store.release_lock(slack_conn.connection_id, job_id="slack_job_1")
    assert slack_store.is_locked(slack_conn.connection_id) is False
    assert notion_store.is_locked(notion_conn.connection_id) is True, "Notion must remain locked until its own release"
    notion_store.release_lock(notion_conn.connection_id, job_id="notion_job_1")
    assert notion_store.is_locked(notion_conn.connection_id) is False

    print(" [PASS] Per-connection isolation verified: Slack & Notion locks are fully independent.")

    print("\n=== TEST 4: SlackSyncManager Rate Limits, Batching & Webhook Simulation ===")
    slack_mgr = SlackSyncManager(store=slack_store)
    # Verify default config limit is 15, bounded at 30
    cfg = SlackSyncConfig()
    assert cfg.max_messages_per_sync == 15, "Slack default limit must be 15"
    bounded_cfg = SlackSyncConfig.from_dict({"max_messages_per_sync": 999})
    assert bounded_cfg.max_messages_per_sync == 30, "Slack max limit must be capped at 30"

    # Simulate webhook ingestion for Slack
    wh_event = normalize_slack({
        "metadata": {"user_id": test_user, "trigger_slug": "SLACKBOT_DIRECT_MESSAGE_RECEIVED"},
        "data": {
            "channel": "D_TEST",
            "user": "U_TEST",
            "user_name": "test_sender",
            "ts": "1710000099.999",
            "text": "Live Webhook message test",
        }
    }, tenant_id=test_tenant)

    wh_res = await slack_mgr.process_webhook_event(wh_event)
    assert wh_res.get("status") == "success", f"Expected success, got {wh_res}"
    assert slack_store.is_message_synced(test_tenant, slack_conn.connection_id, wh_event.external_id) is True
    print(" [PASS] Slack webhook event ingested, deduplicated, and logged in activity.")

    # Deduplication test
    dup_res = await slack_mgr.process_webhook_event(wh_event)
    assert dup_res.get("status") == "ignored", "Duplicate webhook must be ignored"
    print(" [PASS] Slack duplicate webhook successfully ignored.")

    # Composio webhook without user_id in metadata (Slack author U0BKTD5JJ07 in data)
    slack_conn.config.webhook_enabled = True
    slack_conn.webhook_trigger_id = "ti_slack_test"
    slack_conn.status = SlackSyncStatus.CONNECTED
    slack_store.update_connection(slack_conn)

    composio_raw_payload = {
        "metadata": {"trigger_id": "ti_slack_test", "trigger_slug": "SLACKBOT_CHANNEL_MESSAGE_RECEIVED"},
        "data": {
            "channel": "C_GENERAL",
            "channel_name": "general",
            "user": "U0BKTD5JJ07",
            "user_name": "author_user",
            "ts": "1710000100.111",
            "text": "Composio webhook message from Slack author",
        }
    }
    composio_wh_event = normalize_slack(composio_raw_payload, tenant_id=test_tenant)
    # Ensure normalize_slack didn't set event.user_id to the Slack author ID
    assert composio_wh_event.user_id == "", "CanonicalEvent user_id should be empty when app user_id is not in payload metadata"
    assert composio_wh_event.metadata["sender_id"] == "U0BKTD5JJ07"
    assert composio_wh_event.metadata["sender_name"] == "author_user"

    composio_wh_res = await slack_mgr.process_webhook_event(composio_wh_event, raw_payload=composio_raw_payload)
    assert composio_wh_res.get("status") == "success"
    # Ensure message and activity routed to slack_conn, NOT an orphan U0BKTD5JJ07 connection
    assert slack_store.is_message_synced(test_tenant, slack_conn.connection_id, composio_wh_event.external_id) is True
    orphan_conn = slack_store.get_connection(test_tenant, "U0BKTD5JJ07")
    assert orphan_conn is None, "Orphan connection for Slack author U0BKTD5JJ07 must NOT be created!"
    acts = slack_store.get_activities(slack_conn.connection_id)
    assert any(a.trigger_type == SlackTriggerType.WEBHOOK for a in acts), "Webhook activity must be logged under user's connection"
    print(" [PASS] Composio webhook routing verified: routed to user connection via trigger_id/webhook_enabled without creating orphan.")

    print("\n=== TEST 5: NotionSyncManager Rate Limits, Batching & Webhook Simulation ===")
    notion_mgr = NotionSyncManager(store=notion_store)
    # Verify default config limit is 15, bounded at 30
    n_cfg = NotionSyncConfig()
    assert n_cfg.max_records_per_sync == 15, "Notion default limit must be 15"
    n_bounded = NotionSyncConfig.from_dict({"max_records_per_sync": 50})
    assert n_bounded.max_records_per_sync == 30, "Notion max limit must be capped at 30"

    # Simulate webhook ingestion for Notion
    n_wh_event = normalize_notion({
        "metadata": {"user_id": test_user, "trigger_slug": "NOTION_PAGE_CREATED_TRIGGER"},
        "data": {
            "id": "notion_live_page_1",
            "object": "page",
            "title": "Real-time Meeting Minutes",
            "markdown": "Action items: deploy Slack and Notion sync.",
        }
    }, tenant_id=test_tenant)

    n_wh_res = await notion_mgr.process_webhook_event(n_wh_event)
    assert n_wh_res.get("status") == "success", f"Expected success, got {n_wh_res}"
    assert notion_store.is_record_synced(test_tenant, notion_conn.connection_id, "notion_live_page_1") is True
    print(" [PASS] Notion webhook event ingested, deduplicated, and logged in activity.")

    # Deduplication test
    n_dup_res = await notion_mgr.process_webhook_event(n_wh_event)
    assert n_dup_res.get("status") == "ignored", "Duplicate Notion webhook must be ignored"
    print(" [PASS] Notion duplicate webhook successfully ignored.")

    # Composio webhook without user_id in metadata (Notion author in created_by)
    notion_conn.config.webhook_enabled = True
    notion_conn.webhook_trigger_id = "ti_notion_test"
    notion_conn.status = NotionSyncStatus.CONNECTED
    notion_store.update_connection(notion_conn)

    notion_composio_payload = {
        "metadata": {"trigger_id": "ti_notion_test", "trigger_slug": "NOTION_PAGE_UPDATED_TRIGGER"},
        "data": {
            "id": "notion_live_page_2",
            "object": "page",
            "created_by": {"id": "notion_author_uuid_123"},
            "title": "Design Specs V2",
            "markdown": "Updated Notion specs without user_id in metadata.",
        }
    }
    notion_wh_event = normalize_notion(notion_composio_payload, tenant_id=test_tenant)
    assert notion_wh_event.user_id == "", "CanonicalEvent user_id should be empty when app user_id is not in payload metadata"

    notion_wh_res = await notion_mgr.process_webhook_event(notion_wh_event, raw_payload=notion_composio_payload)
    assert notion_wh_res.get("status") == "success"
    assert notion_store.is_record_synced(test_tenant, notion_conn.connection_id, "notion_live_page_2") is True
    orphan_n_conn = notion_store.get_connection(test_tenant, "notion_author_uuid_123")
    assert orphan_n_conn is None, "Orphan connection for Notion author must NOT be created!"
    n_acts = notion_store.get_activities(notion_conn.connection_id)
    assert any(a.trigger_type == NotionTriggerType.WEBHOOK for a in n_acts), "Webhook activity must be logged under user's connection"
    print(" [PASS] Composio Notion webhook routing verified: routed to user connection without creating orphan.")

    print("\n=== TEST 6: Data Purge Isolation ===")
    # Purge Slack data
    purge_slack = await slack_mgr.purge_all_connector_data(user_id=test_user, tenant_id=test_tenant)
    assert purge_slack["status"] == "success"
    assert slack_store.is_message_synced(test_tenant, slack_conn.connection_id, wh_event.external_id) is False
    # Verify Notion data was NOT deleted
    assert notion_store.is_record_synced(test_tenant, notion_conn.connection_id, "notion_live_page_1") is True, "Purging Slack must NOT delete Notion data!"
    print(" [PASS] Data purge isolation confirmed: Slack purge leaves Notion intact.")

    # Purge Notion data
    purge_notion = await notion_mgr.purge_all_connector_data(user_id=test_user, tenant_id=test_tenant)
    assert purge_notion["status"] == "success"
    assert notion_store.is_record_synced(test_tenant, notion_conn.connection_id, "notion_live_page_1") is False
    print(" [PASS] Notion data purge confirmed.")

    print("\n==================================================")
    print(" ALL SLACK & NOTION BACKEND TESTS PASSED CLEANLY! ")
    print("==================================================")

if __name__ == "__main__":
    asyncio.run(run_tests())
