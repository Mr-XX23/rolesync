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
        metadata = payload.get("metadata", {})
        trigger_slug = metadata.get("trigger_slug", "")

        if trigger_slug.startswith("GMAIL_"):
            return normalize_gmail(payload, tenant_id)
        elif trigger_slug.startswith("GOOGLE_DRIVE_") or "DRIVE" in trigger_slug:
            return normalize_gdrive(payload, tenant_id)
        elif trigger_slug.startswith("GOOGLE_CALENDAR_") or "CALENDAR" in trigger_slug:
            return normalize_calendar(payload, tenant_id)
        elif trigger_slug.startswith("SLACK_") or "SLACK" in trigger_slug:
            return normalize_slack(payload, tenant_id)
        elif trigger_slug.startswith("NOTION_") or "NOTION" in trigger_slug:
            return normalize_notion(payload, tenant_id)

        return None
