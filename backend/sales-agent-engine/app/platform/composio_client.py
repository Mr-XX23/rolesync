"""Composio adapter: the existing connections (Gmail, Calendar, Slack, Notion, Drive) that
data-pipeline set up, exposed as async calls. Connections are keyed by Composio
``user_id`` = the auth-service ``userId``, the same identity data-pipeline uses.

The SDK is synchronous, so every call runs in a worker thread. Toolkit versions are
pinned from settings so a Composio schema change cannot silently alter a tool.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


class ConnectorError(Exception):
    """A connector call failed; the message is safe to show to the agent and the user."""


class ConnectorOutcomeUnknown(ConnectorError):
    """The call raised before a response arrived, so whether it took effect is unknown."""


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
            # No answer came back: the call may or may not have reached the provider.
            raise ConnectorOutcomeUnknown(f"{slug} gave no answer: {type(exc).__name__}: {str(exc)[:200]}") from exc
        if not response.get("successful"):
            raise ConnectorError(f"{slug} failed: {str(response.get('error') or 'unknown error')[:300]}")
        return dict(response.get("data") or {})

    async def stage_file(self, *, slug: str, filename: str, content: bytes, mimetype: str) -> dict[str, str]:
        """Upload file bytes for a tool's file input (e.g. ``GOOGLEDRIVE_UPLOAD_FILE``) and return the
        ``{name, mimetype, s3key}`` descriptor to pass as that argument. Nothing reaches the
        user's account until the tool itself runs."""
        toolkit = slug.split("_", 1)[0].lower()

        def stage() -> dict[str, str]:
            from composio.core.models._files import FileUploadable

            # Only this private folder may be read by the SDK's uploader.
            with tempfile.TemporaryDirectory(prefix="rolesync-upload-") as folder:
                path = Path(folder) / filename
                path.write_bytes(content)
                staged = FileUploadable.from_path(
                    self._sdk.client, path, slug, toolkit, file_upload_allowlist=[Path(folder)]
                )
                return {"name": staged.name, "mimetype": mimetype or staged.mimetype, "s3key": staged.s3key}

        try:
            return await asyncio.to_thread(stage)
        except Exception as exc:
            raise ConnectorError(f"could not prepare {filename} for upload: {type(exc).__name__}: {str(exc)[:200]}") from exc
