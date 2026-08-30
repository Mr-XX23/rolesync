from datetime import datetime
from connectors.events.canonical_event import EventType
from connectors.normalizers.gmail_normalizer import normalize_gmail
from connectors.normalizers.gdrive_normalizer import normalize_gdrive
from connectors.normalizers.calendar_normalizer import normalize_calendar
from connectors.normalizers.slack_normalizer import normalize_slack
from connectors.normalizers.notion_normalizer import normalize_notion

def test_normalize_gmail():
    payload = {
        "metadata": {
            "log_id": "log_gmail_123",
            "trigger_slug": "GMAIL_NEW_GMAIL_MESSAGE",
            "user_id": "user_100",
            "connected_account_id": "acc_1",
        },
        "data": {
            "message_id": "msg_999",
            "thread_id": "th_888",
            "to": "alice@example.com",
            "sender": "bob@example.com",
            "subject": "Project Sync",
            "message_timestamp": "2026-08-23T10:00:00Z",
        },
    }
    event = normalize_gmail(payload, tenant_id="tenant_alpha")
    assert event.source == "gmail"
    assert event.event_type == EventType.CREATE
    assert event.tenant_id == "tenant_alpha"
    assert event.user_id == "user_100"
    assert "alice@example.com" in event.acl
    assert event.metadata["subject"] == "Project Sync"

def test_normalize_gdrive():
    payload = {
        "metadata": {
            "log_id": "log_gdrive_456",
            "trigger_slug": "GOOGLE_DRIVE_FILE_CREATED",
            "user_id": "user_200",
        },
        "data": {
            "id": "file_doc_11",
            "name": "Q3_Report.pdf",
            "mimeType": "application/pdf",
            "size": 1048576,
            "permissions": [{"emailAddress": "carol@example.com"}],
            "modifiedTime": "2026-08-23T11:00:00Z",
        },
    }
    event = normalize_gdrive(payload, tenant_id="tenant_alpha")
    assert event.source == "gdrive"
    assert event.event_type == EventType.CREATE
    assert event.external_id == "file_doc_11"
    assert "carol@example.com" in event.acl
    assert event.metadata["name"] == "Q3_Report.pdf"

def test_normalize_calendar():
    payload = {
        "metadata": {
            "log_id": "log_cal_789",
            "trigger_slug": "GOOGLE_CALENDAR_EVENT_UPDATED",
            "user_id": "user_300",
        },
        "data": {
            "id": "evt_call_55",
            "summary": "Sprint Planning",
            "description": "Weekly sync",
            "attendees": [{"email": "dev1@example.com"}, {"email": "dev2@example.com"}],
            "start": {"dateTime": "2026-08-24T09:00:00Z"},
            "end": {"dateTime": "2026-08-24T10:00:00Z"},
        },
    }
    event = normalize_calendar(payload, tenant_id="tenant_alpha")
    assert event.source == "google_calendar"
    assert event.event_type == EventType.UPDATE
    assert "dev1@example.com" in event.acl
    assert event.metadata["summary"] == "Sprint Planning"

def test_normalize_slack():
    payload = {
        "metadata": {
            "log_id": "log_slack_001",
            "trigger_slug": "SLACK_NEW_MESSAGE",
            "user_id": "U123456",
        },
        "data": {
            "channel": "C999999",
            "user": "U123456",
            "text": "Hello team!",
            "ts": "1724400000.000100",
        },
    }
    event = normalize_slack(payload, tenant_id="tenant_alpha")
    assert event.source == "slack"
    assert event.event_type == EventType.CREATE
    assert event.user_id == "U123456"
    assert "channel:C999999" in event.acl
    assert event.metadata["text"] == "Hello team!"

def test_normalize_notion():
    payload = {
        "metadata": {
            "log_id": "log_notion_333",
            "trigger_slug": "NOTION_PAGE_UPDATED",
            "user_id": "notion_usr_1",
        },
        "data": {
            "id": "page_notion_abc",
            "object": "page",
            "url": "https://notion.so/page_notion_abc",
            "properties": {
                "Title": {
                    "type": "title",
                    "title": [{"plain_text": "Architecture Spec"}],
                }
            },
            "last_edited_time": "2026-08-23T12:00:00Z",
        },
    }
    event = normalize_notion(payload, tenant_id="tenant_alpha")
    assert event.source == "notion"
    assert event.event_type == EventType.UPDATE
    assert event.external_id == "page_notion_abc"
    assert event.metadata["title"] == "Architecture Spec"
