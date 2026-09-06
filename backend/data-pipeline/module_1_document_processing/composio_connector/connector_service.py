from typing import Any
from module_1_document_processing.composio_connector.composio_client import ComposioClient

class ConnectorService:
    """Service handling multi-tenant source connectors (Gmail, GDrive, Calendar, Slack, Notion)."""

    def __init__(self, composio_client: ComposioClient | None = None) -> None:
        self.client = composio_client or ComposioClient()
        self.composio = self.client

    def connect_source(self, user_id: str, source: str, callback_url: str | None = None, enable_webhook: bool = False) -> dict[str, Any]:
        trigger_map = {
            "gmail": ComposioClient.GMAIL_NEW_MESSAGE,
            "gdrive": ComposioClient.GDRIVE_FILE_CREATED,
            "google_drive": ComposioClient.GDRIVE_FILE_CREATED,
            "googledrive": ComposioClient.GDRIVE_FILE_CREATED,
            "google_calendar": ComposioClient.CALENDAR_EVENT_UPDATED,
            "calendar": ComposioClient.CALENDAR_EVENT_UPDATED,
            "slack": ComposioClient.SLACK_NEW_MESSAGE,
            "notion": ComposioClient.NOTION_PAGE_UPDATED,
        }

        slug = trigger_map.get(source.lower())
        if not slug:
            return {"status": "error", "message": f"Unsupported connector source '{source}'"}

        redirect_url = self.client.initiate_user_connection(user_id=user_id, source=source, callback_url=callback_url)
        trigger_id = None
        if enable_webhook:
            trigger_id = self.client.enable_trigger(trigger_slug=slug, user_id=user_id)

        return {
            "status": "success",
            "source": source,
            "user_id": user_id,
            "trigger_id": trigger_id,
            "redirect_url": redirect_url,
        }
