from connectors.composio_client import ComposioClient
from connectors.normalizers.gmail_normalizer import normalize_gmail
from connectors.events.canonical_event import CanonicalEvent

class ConnectorService:
    def __init__(self, client: ComposioClient | None = None) -> None:
        self._client = client or ComposioClient()

    def connect_gmail(self, user_id: str) -> str:
        return self._client.create_gmail_trigger(user_id)

    def handle_webhook(self, body: bytes, headers, tenant_id: str) -> CanonicalEvent | None:
        payload = self._client.parse_webhook(body, headers)
        if payload is None:
            return None

        slug = payload["metadata"]["trigger_slug"]
        if slug == ComposioClient.GMAIL_NEW_MESSAGE:
            return normalize_gmail(payload, tenant_id)

        return None  # unknown slug — ignore for now (Slack/Drive added later)