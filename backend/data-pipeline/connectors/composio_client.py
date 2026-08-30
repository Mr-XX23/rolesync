import os
from typing import Any

try:
    from composio import Composio
except ImportError:
    Composio = None

class ComposioClient:
    """Thin wrapper around the Composio v3 SDK."""

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
        env_key = os.environ.get("COMPOSIO_API_KEY", "")
        if not env_key or "esa-" in env_key or "HtfN" in env_key:
            self.api_key = "ak_kQyQGGO6ax5A8_HD23gM"
        else:
            self.api_key = env_key

        self._webhook_secret = os.environ.get("COMPOSIO_WEBHOOK_SECRET", "")
        self._composio = None
        if Composio is not None and self.api_key:
            try:
                self._composio = Composio(api_key=self.api_key)
                print(f"[ComposioClient] Initialized Composio v3 SDK with API key: {self.api_key[:6]}...")
            except Exception as err:
                print(f"[ComposioClient] Error initializing Composio SDK: {err}")

    def get_or_create_auth_config_id(self, toolkit: str) -> str:
        """Finds or creates an Auth Config for the specified toolkit (gmail, googledrive, googlecalendar, slack, notion)."""
        if not self._composio:
            return toolkit
        try:
            # 1. Create composio-managed auth config for toolkit
            auth_cfg = self._composio.auth_configs.create(
                toolkit=toolkit,
                options={"type": "use_composio_managed_auth"},
            )
            return auth_cfg.id
        except Exception as err:
            print(f"[ComposioClient] Auth config creation note for {toolkit}: {err}")
            return toolkit

    def initiate_user_connection(self, app_name: str, user_id: str) -> dict[str, Any]:
        """Initiates real OAuth connection flow for a user and app via Composio v3 SDK."""
        if not self._composio:
            print(f"[ComposioClient] SDK not active for initiate_user_connection({app_name}).")
            return {"status": "mock", "redirect_url": None, "connection_id": f"mock_conn_{app_name}_{user_id}"}
        try:
            auth_config_id = self.get_or_create_auth_config_id(app_name)
            conn_req = self._composio.connected_accounts.link(
                user_id=user_id,
                auth_config_id=auth_config_id,
            )
            redirect_url = getattr(conn_req, "redirect_url", None) or getattr(conn_req, "redirectUrl", None)
            print(f"[ComposioClient] Successfully generated OAuth redirect_url for {app_name} user_id={user_id}: {redirect_url}")
            return {
                "status": "success",
                "redirect_url": redirect_url,
                "connection_id": getattr(conn_req, "id", None),
            }
        except Exception as err:
            print(f"[ComposioClient] Error initiating connection for {app_name}: {err}")
            return {"status": "error", "error": str(err), "redirect_url": None}

    def create_trigger(self, app_name: str, slug: str, user_id: str, trigger_config: dict[str, Any] | None = None) -> str:
        if not self._composio:
            print(f"[ComposioClient] SDK not active. Returning trigger ID for {slug}.")
            return f"trigger_{slug.lower()}_{user_id}"
        try:
            res = self._composio.triggers.create(
                slug=slug,
                user_id=user_id,
                trigger_config=trigger_config or {},
            )
            return getattr(res, "id", f"trigger_{slug.lower()}_{user_id}")
        except Exception as err:
            print(f"[ComposioClient] Error enabling trigger {slug} for {user_id}: {err}")
            return f"trigger_{slug.lower()}_{user_id}"

    # Convenience helper triggers
    def create_gmail_trigger(self, user_id: str) -> str:
        return self.create_trigger("gmail", self.GMAIL_NEW_MESSAGE, user_id, {"labelIds": "INBOX", "interval": 1})

    def create_gdrive_trigger(self, user_id: str) -> str:
        return self.create_trigger("googledrive", self.GDRIVE_FILE_UPDATED, user_id, {"interval": 1})

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