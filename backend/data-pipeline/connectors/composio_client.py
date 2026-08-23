import os
try:
    from composio import Composio
except ImportError:
    Composio = None

class ComposioClient:
    """Thin wrapper around the Composio SDK. Nothing else in the app
    imports `composio` directly — only this class."""

    GMAIL_NEW_MESSAGE = "GMAIL_NEW_GMAIL_MESSAGE"

    def __init__(self) -> None:
        # Reads COMPOSIO_API_KEY and COMPOSIO_WEBHOOK_SECRET directly from environment (.env)
        self._composio = Composio() if Composio is not None else None
        self._webhook_secret = os.environ.get("COMPOSIO_WEBHOOK_SECRET", "")

    # ---- connection / trigger setup ----
    def create_gmail_trigger(self, user_id: str) -> str:
        if not self._composio:
            return ""
        trigger = self._composio.triggers.create(
            slug=self.GMAIL_NEW_MESSAGE,
            user_id=user_id,
            trigger_config={"labelIds": "INBOX", "interval": 1},
        )
        return trigger.trigger_id
    
    def register_webhook(self, url: str) -> dict:
        if not self._composio:
            return {}
        return self._composio.triggers.set_webhook_subscription(webhook_url=url)

    # ---- inbound webhook parsing (verifies signature + replay window) ----
    def parse_webhook(self, body: bytes, headers) -> dict | None:
        if not self._composio:
            return None
        result = self._composio.triggers.parse(
            body=body,
            headers=headers,
            verify_secret=self._webhook_secret,
        )
        if result["raw_payload"]["type"] != "composio.trigger.message":
            return None            
        return result["payload"]