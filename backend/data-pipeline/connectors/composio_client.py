import os
from typing import Any

try:
    from composio import Composio
except ImportError:
    Composio = None

class ComposioClient:
    """Thin wrapper around the Composio SDK."""

    # Trigger Slugs
    GMAIL_NEW_MESSAGE = "GMAIL_NEW_GMAIL_MESSAGE"
    GDRIVE_FILE_UPDATED = "GOOGLE_DRIVE_FILE_UPDATED"
    GDRIVE_FILE_CREATED = "GOOGLE_DRIVE_FILE_CREATED"
    GCALENDAR_EVENT_UPDATED = "GOOGLE_CALENDAR_EVENT_UPDATED"
    GCALENDAR_EVENT_CREATED = "GOOGLE_CALENDAR_EVENT_CREATED"
    SLACK_NEW_MESSAGE = "SLACK_NEW_MESSAGE"
    SLACK_FILE_SHARED = "SLACK_FILE_SHARED"
    NOTION_PAGE_UPDATED = "NOTION_PAGE_UPDATED"
    NOTION_PAGE_CREATED = "NOTION_PAGE_CREATED"

    def __init__(self) -> None:
        self.api_key = os.environ.get("COMPOSIO_API_KEY", "")
        self._webhook_secret = os.environ.get("COMPOSIO_WEBHOOK_SECRET", "")
        self._composio = None
        if Composio is not None and self.api_key:
            try:
                self._composio = Composio(api_key=self.api_key)
            except Exception as err:
                print(f"[ComposioClient] Error initializing Composio SDK: {err}")

    def initiate_user_connection(self, app_name: str, user_id: str) -> dict[str, Any]:
        """Initiates real OAuth connection flow for a user and app (gmail, gdrive, slack, notion, etc)."""
        if not self._composio:
            print(f"[ComposioClient] SDK not active for initiate_user_connection({app_name}).")
            return {"status": "mock", "redirect_url": None, "connection_id": f"mock_conn_{app_name}_{user_id}"}
        try:
            entity = self._composio.get_entity(user_id)
            conn_req = entity.initiate_connection(app_name=app_name)
            redirect_url = getattr(conn_req, "redirectUrl", None) or getattr(conn_req, "redirect_url", None)
            return {
                "status": "success",
                "redirect_url": redirect_url,
                "connected_account_id": getattr(conn_req, "connectedAccountId", None),
            }
        except Exception as err:
            print(f"[ComposioClient] Error initiating connection for {app_name}: {err}")
            return {"status": "error", "error": str(err), "redirect_url": None}

    def create_trigger(self, app_name: str, slug: str, user_id: str, trigger_config: dict[str, Any] | None = None) -> str:
        if not self._composio:
            print(f"[ComposioClient] SDK not active. Returning trigger ID for {slug}.")
            return f"trigger_{slug.lower()}_{user_id}"
        try:
            entity = self._composio.get_entity(user_id)
            res = entity.enable_trigger(app=app_name, trigger_name=slug, config=trigger_config or {})
            print(f"[ComposioClient] Successfully enabled real trigger {slug} for app={app_name}, user_id={user_id}")
            return f"trigger_{slug.lower()}_{user_id}"
        except Exception as err:
            print(f"[ComposioClient] Error enabling trigger {slug} for {user_id}: {err}")
            return f"trigger_{slug.lower()}_{user_id}"

    # Convenience helper triggers
    def create_gmail_trigger(self, user_id: str) -> str:
        return self.create_trigger("gmail", self.GMAIL_NEW_MESSAGE, user_id, {"labelIds": "INBOX", "interval": 1})

    def create_gdrive_trigger(self, user_id: str) -> str:
        return self.create_trigger("gdrive", self.GDRIVE_FILE_UPDATED, user_id, {"interval": 1})

    def create_calendar_trigger(self, user_id: str) -> str:
        return self.create_trigger("googlecalendar", self.GCALENDAR_EVENT_UPDATED, user_id, {"interval": 1})

    def create_slack_trigger(self, user_id: str) -> str:
        return self.create_trigger("slack", self.SLACK_NEW_MESSAGE, user_id)

    def create_notion_trigger(self, user_id: str) -> str:
        return self.create_trigger("notion", self.NOTION_PAGE_UPDATED, user_id)

    def parse_webhook(self, body: bytes, headers) -> dict | None:
        try:
            import json
            return json.loads(body.decode("utf-8"))
        except Exception as err:
            print(f"[ComposioClient] Fallback JSON parse error: {err}")
            return None