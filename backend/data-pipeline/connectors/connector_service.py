from typing import Any
from connectors.composio_client import ComposioClient
from connectors.events.canonical_event import CanonicalEvent
from connectors.normalizers.gmail_normalizer import normalize_gmail
from connectors.normalizers.gdrive_normalizer import normalize_gdrive
from connectors.normalizers.calendar_normalizer import normalize_calendar
from connectors.normalizers.slack_normalizer import normalize_slack
from connectors.normalizers.notion_normalizer import normalize_notion

class ConnectorService:
    def __init__(self, client: ComposioClient | None = None) -> None:
        self._client = client or ComposioClient()

    def connect_source_with_auth(self, source: str, user_id: str) -> dict[str, Any]:
        source_lower = source.lower()
        
        # Map frontend source names to Composio Toolkit names
        app_map = {
            "gmail": "gmail",
            "gdrive": "googledrive",
            "google_drive": "googledrive",
            "googledrive": "googledrive",
            "drive": "googledrive",
            "calendar": "googlecalendar",
            "gcalendar": "googlecalendar",
            "google_calendar": "googlecalendar",
            "slack": "slack",
            "notion": "notion",
        }

        if source_lower not in app_map:
            raise ValueError(f"Unsupported connector source: {source}")

        app_name = app_map[source_lower]

        # 1. Initiate OAuth connection for real user redirect if needed
        conn_res = self._client.initiate_user_connection(app_name=app_name, user_id=user_id)
        redirect_url = conn_res.get("redirect_url")

        # 2. Enable real trigger
        trigger_id = self.connect_source(source=source_lower, user_id=user_id)

        return {
            "trigger_id": trigger_id,
            "redirect_url": redirect_url,
        }

    def connect_source(self, source: str, user_id: str) -> str:
        source_lower = source.lower()
        if source_lower == "gmail":
            return self._client.create_gmail_trigger(user_id)
        elif source_lower in ("gdrive", "google_drive", "drive", "googledrive"):
            return self._client.create_gdrive_trigger(user_id)
        elif source_lower in ("gcalendar", "google_calendar", "calendar"):
            return self._client.create_calendar_trigger(user_id)
        elif source_lower == "slack":
            return self._client.create_slack_trigger(user_id)
        elif source_lower == "notion":
            return self._client.create_notion_trigger(user_id)
        else:
            raise ValueError(f"Unsupported connector source: {source}")

    def handle_webhook(self, body: bytes, headers, tenant_id: str) -> CanonicalEvent | None:
        payload = self._client.parse_webhook(body, headers)
        if payload is None:
            return None

        slug = payload.get("metadata", {}).get("trigger_slug", "")
        
        if slug.startswith("GMAIL_") or slug == ComposioClient.GMAIL_NEW_MESSAGE:
            return normalize_gmail(payload, tenant_id)
        elif slug.startswith("GOOGLE_DRIVE_") or "DRIVE" in slug:
            return normalize_gdrive(payload, tenant_id)
        elif slug.startswith("GOOGLE_CALENDAR_") or "CALENDAR" in slug:
            return normalize_calendar(payload, tenant_id)
        elif slug.startswith("SLACK_") or "SLACK" in slug:
            return normalize_slack(payload, tenant_id)
        elif slug.startswith("NOTION_") or "NOTION" in slug:
            return normalize_notion(payload, tenant_id)

        return None