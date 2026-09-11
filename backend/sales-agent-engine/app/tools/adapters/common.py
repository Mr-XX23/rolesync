"""Helpers shared by tool adapters: connection checks, connector calls, compact results."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.core.context import AgentContext
from app.platform.composio_client import ConnectorClient, ConnectorError, ConnectorOutcomeUnknown
from app.platform.data_pipeline import DataPipelineError
from app.platform.workspace_client import WorkspaceDirectory
from app.tools.registry import AclCheck
from app.tools.types import ToolAccessDenied, ToolFailed, ToolInput, ToolOutcomeUnknown


def connection_required(connector: ConnectorClient, toolkit: str, label: str) -> AclCheck:
    """ACL: the user must have connected this app (connections are per auth user)."""

    async def check(ctx: AgentContext, args: ToolInput) -> None:
        try:
            connected = await connector.has_active_connection(ctx.user_id, toolkit)
        except ConnectorError as exc:
            raise ToolFailed(str(exc), retryable=True) from exc
        if not connected:
            raise ToolAccessDenied(f"{label} is not connected for this user; connect it under Connectors first")

    return check


def workspace_writer_required(directory: WorkspaceDirectory, what: str) -> AclCheck:
    """ACL: the user may change shared workspace data (every member except viewers)."""

    async def check(ctx: AgentContext, args: ToolInput) -> None:
        role = await directory.role_in(ctx.user_id, ctx.tenant_id)
        if role is None:
            raise ToolAccessDenied("you are no longer a member of this workspace")
        if role == "VIEWER":
            raise ToolAccessDenied(f"viewers can't change {what}; ask a workspace owner or admin")

    return check


async def run_connector(connector: ConnectorClient, *, user_id: UUID, slug: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """A read through the connector; its failures are ordinary tool failures (no answer: worth a retry)."""
    try:
        return await connector.execute(user_id=user_id, slug=slug, arguments=arguments)
    except ConnectorError as exc:
        raise ToolFailed(str(exc), retryable=isinstance(exc, ConnectorOutcomeUnknown)) from exc


async def run_connector_write(
    connector: ConnectorClient, *, user_id: UUID, slug: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """A write through the connector: without an answer it may have happened, so it is UNKNOWN."""
    try:
        return await connector.execute(user_id=user_id, slug=slug, arguments=arguments)
    except ConnectorOutcomeUnknown as exc:
        raise ToolOutcomeUnknown(str(exc)) from exc
    except ConnectorError as exc:
        raise ToolFailed(str(exc)) from exc


async def run_connector_undo(
    connector: ConnectorClient, *, user_id: UUID, slug: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """An undo step: written to be safe to repeat, so a missing answer is worth a retry."""
    return await run_connector(connector, user_id=user_id, slug=slug, arguments=arguments)


def pipeline_failure(exc: DataPipelineError) -> Exception:
    """A data-pipeline error on a read or an undo step, as a tool error."""
    if exc.status == 403:
        return ToolAccessDenied(str(exc))
    return ToolFailed(str(exc), retryable=exc.retryable)


def pipeline_write_failure(exc: DataPipelineError) -> Exception:
    """A data-pipeline error on a write: no answer after sending means it may have happened."""
    if exc.maybe_applied:
        return ToolOutcomeUnknown(str(exc))
    if exc.status == 403:
        return ToolAccessDenied(str(exc))
    return ToolFailed(str(exc))


def clip(value: Any, limit: int) -> str:
    """Text for a model's context: at most ``limit`` characters, marked when cut."""
    text = value.strip() if isinstance(value, str) else ""
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def as_utc(moment: datetime) -> datetime:
    """The same instant in UTC; a time without a zone is taken to be UTC."""
    return (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).astimezone(UTC)


def utc_rfc3339(moment: datetime) -> str:
    return as_utc(moment).isoformat().replace("+00:00", "Z")


def plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def first_dict(data: dict[str, Any], *keys: str) -> dict[str, Any]:
    """Composio nests provider responses differently per tool and version (``data``,
    ``response_data``, ...): the first nested dict under ``keys``, else ``data`` itself."""
    for key in keys:
        candidate = data.get(key)
        if isinstance(candidate, dict) and candidate:
            return candidate
    return data


_UNSAFE_FILENAME = re.compile(r"[^\w.\- ()&,+]+", re.UNICODE)


def safe_filename(name: str, extension: str, *, limit: int = 120) -> str:
    """A file name that is safe on every platform, with the given extension."""
    stem = _UNSAFE_FILENAME.sub(" ", name).strip(" .") or "document"
    stem = re.sub(r"\s+", " ", stem)[:limit].rstrip(" .")
    return f"{stem}.{extension}"
