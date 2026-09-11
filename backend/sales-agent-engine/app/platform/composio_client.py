"""Composio adapter: the existing connections (Gmail, Calendar, Slack, Notion, Drive) that
data-pipeline set up, exposed as async calls. Connections are keyed by Composio
``user_id`` = the auth-service ``userId``, the same identity data-pipeline uses.

The SDK is synchronous, so every call runs in a worker thread. Toolkit versions are
pinned from settings so a Composio schema change cannot silently alter a tool.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


class ConnectorError(Exception):
    """A connector call failed; the message is safe to show to the agent and the user."""


class ConnectorClient:
    def __init__(self, *, api_key: str, toolkit_versions: Mapping[str, str], connection_cache_seconds: int = 60) -> None:
        from composio import Composio

        self._sdk = Composio(api_key=api_key, toolkit_versions=dict(toolkit_versions))
        self._pins = dict(toolkit_versions)
        self._cache_ttl = connection_cache_seconds
        self._active_since: dict[tuple[str, str], float] = {}

    async def has_active_connection(self, user_id: UUID, toolkit: str) -> bool:
        # Only positive answers are cached: someone who just connected must not wait out a TTL.
        key = (str(user_id), toolkit.lower())
        seen = self._active_since.get(key)
        if seen is not None and time.monotonic() - seen < self._cache_ttl:
            return True
        try:
            accounts = await asyncio.to_thread(
                self._sdk.connected_accounts.list, user_ids=[str(user_id)], toolkit_slugs=[toolkit.lower()]
            )
        except Exception as exc:
            raise ConnectorError(f"could not check the {toolkit} connection: {type(exc).__name__}") from exc
        items = getattr(accounts, "items", accounts) or []
        active = any(str(getattr(account, "status", "")).upper() == "ACTIVE" for account in items)
        if active:
            self._active_since[key] = time.monotonic()
        return active

    async def execute(self, *, user_id: UUID, slug: str, arguments: dict[str, Any]) -> dict[str, Any]:
        toolkit = slug.split("_", 1)[0].lower()
        options: dict[str, Any] = {"user_id": str(user_id)}
        if toolkit not in self._pins:
            logger.warning("no pinned Composio version for toolkit %s; using latest", toolkit)
            options["dangerously_skip_version_check"] = True
        try:
            response = await asyncio.to_thread(self._sdk.tools.execute, slug, arguments, **options)
        except Exception as exc:
            raise ConnectorError(f"{slug} could not be executed: {type(exc).__name__}: {str(exc)[:200]}") from exc
        if not response.get("successful"):
            raise ConnectorError(f"{slug} failed: {str(response.get('error') or 'unknown error')[:300]}")
        return dict(response.get("data") or {})
