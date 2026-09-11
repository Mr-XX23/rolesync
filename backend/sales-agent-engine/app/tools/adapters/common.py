"""Helpers shared by tool adapters: connection checks, connector calls, compact results."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.core.context import AgentContext
from app.platform.composio_client import ConnectorClient, ConnectorError
from app.tools.registry import AclCheck
from app.tools.types import ToolAccessDenied, ToolFailed, ToolInput


def connection_required(connector: ConnectorClient, toolkit: str, label: str) -> AclCheck:
    """ACL: the user must have connected this app (connections are per auth user)."""

    async def check(ctx: AgentContext, args: ToolInput) -> None:
        try:
            connected = await connector.has_active_connection(ctx.user_id, toolkit)
        except ConnectorError as exc:
            raise ToolFailed(str(exc)) from exc
        if not connected:
            raise ToolAccessDenied(f"{label} is not connected for this user; connect it under Connectors first")

    return check


async def run_connector(connector: ConnectorClient, *, user_id: UUID, slug: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """A read through the connector; its failures are ordinary tool failures."""
    try:
        return await connector.execute(user_id=user_id, slug=slug, arguments=arguments)
    except ConnectorError as exc:
        raise ToolFailed(str(exc)) from exc


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
