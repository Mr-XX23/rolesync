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
        metadata = payload.get("metadata", {}) if isinstance(payload.get("metadata"), dict) else {}
        trigger_slug = (
            metadata.get("trigger_slug", "")
            or payload.get("trigger_slug", "")
            or payload.get("trigger_name", "")
            or payload.get("type", "")
            or payload.get("toolkit_slug", "")
        )

        slug_upper = str(trigger_slug).upper()
        if slug_upper.startswith("GMAIL_") or "GMAIL" in slug_upper:
            return normalize_gmail(payload, tenant_id)
        elif slug_upper.startswith("GOOGLE_DRIVE_") or "DRIVE" in slug_upper:
            return normalize_gdrive(payload, tenant_id)
        elif slug_upper.startswith("GOOGLE_CALENDAR_") or "CALENDAR" in slug_upper:
            return normalize_calendar(payload, tenant_id)
        elif slug_upper.startswith("SLACK_") or "SLACK" in slug_upper:
            return normalize_slack(payload, tenant_id)
        elif slug_upper.startswith("NOTION_") or "NOTION" in slug_upper:
            return normalize_notion(payload, tenant_id)

        return None
