from typing import Any
from module_1_document_processing.composio_connector.events.canonical_event import CanonicalEvent
from module_1_document_processing.composio_connector.normalizers.gmail_normalizer import normalize_gmail
from module_1_document_processing.composio_connector.normalizers.gdrive_normalizer import normalize_gdrive
from module_1_document_processing.composio_connector.normalizers.calendar_normalizer import normalize_calendar
from module_1_document_processing.composio_connector.normalizers.slack_normalizer import normalize_slack
from module_1_document_processing.composio_connector.normalizers.notion_normalizer import normalize_notion

class EventRouter:
    """Routes incoming raw webhook payloads to their respective source normalizers."""

    def route_payload(self, payload: dict[str, Any], tenant_id: str = "tenant_default") -> CanonicalEvent | None:
        if not isinstance(payload, dict):
            return None

        metadata = payload.get("metadata", {}) if isinstance(payload.get("metadata"), dict) else {}
        toolkit = payload.get("toolkit", {}) if isinstance(payload.get("toolkit"), dict) else {}
        toolkit_slug = str(toolkit.get("slug") or payload.get("toolkit_slug") or "").lower()

        trigger_slug = str(
            metadata.get("trigger_slug", "")
            or payload.get("trigger_slug", "")
            or payload.get("trigger_name", "")
            or payload.get("type", "")
            or toolkit_slug
        ).upper()

        inner_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        inner_event_type = str(inner_payload.get("event_type", "") or payload.get("event_type", "")).lower()

        # 1. Gmail routing
        if (
            "GMAIL" in trigger_slug
            or toolkit_slug == "gmail"
            or "messages" in payload
            or "messages" in inner_payload
            or inner_event_type in ("new_gmail_message", "new_message")
        ):
            return normalize_gmail(payload, tenant_id)

        # 2. Google Drive routing
        if (
            "DRIVE" in trigger_slug
            or toolkit_slug in ("googledrive", "gdrive")
            or "file" in payload
            or "file" in inner_payload
            or "file_id" in payload
            or "file_id" in inner_payload
            or inner_event_type in ("file_created", "file_updated", "file_deleted", "trashed", "removed")
            or ("kind" in inner_payload and "drive#change" in str(inner_payload.get("kind", "")))
        ):
            return normalize_gdrive(payload, tenant_id)

        # 3. Google Calendar routing
        if (
            "CALENDAR" in trigger_slug
            or toolkit_slug in ("googlecalendar", "calendar")
            or "calendar" in inner_event_type
        ):
            return normalize_calendar(payload, tenant_id)

        # 4. Slack routing
        if (
            "SLACK" in trigger_slug
            or toolkit_slug in ("slack", "slackbot")
            or "slack" in inner_event_type
            or ("channel" in payload and "ts" in payload)
            or ("channel" in inner_payload and "ts" in inner_payload)
        ):
            return normalize_slack(payload, tenant_id)

        # 5. Notion routing
        if (
            "NOTION" in trigger_slug
            or toolkit_slug == "notion"
            or "notion" in inner_event_type
            or ("object" in payload and payload.get("object") in ("page", "database", "block", "comment"))
            or ("object" in inner_payload and inner_payload.get("object") in ("page", "database", "block", "comment"))
        ):
            return normalize_notion(payload, tenant_id)

        return None
