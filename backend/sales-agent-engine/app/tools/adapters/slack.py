"""Slack over Composio: search messages, post a message (undo: delete it)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from pydantic import Field

from app.core.context import AgentContext
from app.platform.composio_client import ConnectorClient
from app.tools.adapters.common import (
    as_dict,
    as_list,
    clip,
    connection_required,
    first_dict,
    plural,
    run_connector,
    run_connector_undo,
    run_connector_write,
)
from app.tools.registry import ToolDefinition
from app.tools.types import (
    SourceLink,
    ToolCategory,
    ToolFailed,
    ToolInput,
    ToolInvocation,
    ToolKind,
    ToolOutput,
    ToolScope,
    UndoInvocation,
    UndoPlan,
)

_CHANNEL_ID = re.compile(r"^[CDG][A-Z0-9]{8,}$")


class SearchSlackArgs(ToolInput):
    query: str = Field(
        min_length=1,
        max_length=300,
        description="Slack search, e.g. 'acme renewal', 'in:#sales acme', 'from:@jane after:2026-01-01'",
    )
    max_results: int = Field(default=10, ge=1, le=25)


class SendSlackMessageArgs(ToolInput):
    channel: str = Field(
        min_length=1, max_length=100, description="Channel name without '#' (e.g. 'sales'), or a channel or DM id"
    )
    text: str = Field(min_length=1, max_length=12_000, description="The message, in Markdown")
    thread_ts: str | None = Field(
        default=None, pattern=r"^\d+\.\d+$", description="Reply in the thread of this message (its ts)"
    )


def slack_tools(connector: ConnectorClient) -> list[ToolDefinition]:
    require_slack = connection_required(connector, "slack", "Slack")

    async def search_slack_messages(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, SearchSlackArgs)
        data = await run_connector(
            connector,
            user_id=invocation.ctx.user_id,
            slug="SLACK_SEARCH_MESSAGES",
            arguments={"query": args.query, "count": args.max_results, "sort": "timestamp", "sort_dir": "desc"},
        )
        matches = [as_dict(item) for item in as_list(as_dict(data.get("messages")).get("matches"))]
        messages = [_message(match) for match in matches[: args.max_results]]
        return ToolOutput(
            data={"messages": messages},
            summary=f"{plural(len(messages), 'Slack message')} matching '{args.query}'",
            sources=tuple(
                SourceLink(title=f"#{m['channel']}" if m["channel"] else "Slack message", url=m["link"])
                for m in messages[:5]
                if m["link"]
            ),
        )

    async def send_slack_message(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, SendSlackMessageArgs)
        channel = args.channel.strip().lstrip("#")
        arguments: dict[str, Any] = {"channel": channel, "markdown_text": args.text}
        if args.thread_ts:
            arguments["thread_ts"] = args.thread_ts
        data = await run_connector_write(
            connector, user_id=invocation.ctx.user_id, slug="SLACK_SEND_MESSAGE", arguments=arguments
        )
        body = first_dict(data, "response_data", "data")
        message = as_dict(body.get("message"))
        channel_id = str(body.get("channel") or message.get("channel") or "") or None
        ts = str(body.get("ts") or message.get("ts") or "") or None
        where = channel if _CHANNEL_ID.match(channel) else f"#{channel}"
        return ToolOutput(
            data={"channel": channel_id or channel, "ts": ts, "thread_ts": args.thread_ts},
            summary=f"Slack message posted to {where}" + (" (in a thread)" if args.thread_ts else ""),
            ref_id=ts,
            undo=UndoPlan(
                args={"channel": channel_id, "ts": ts},
                label=f"Delete the Slack message in {where} (people may already have read it)",
            )
            if channel_id and ts
            else None,
        )

    async def delete_message(invocation: UndoInvocation) -> str:
        try:
            await run_connector_undo(
                connector,
                user_id=invocation.ctx.user_id,
                slug="SLACK_DELETES_A_MESSAGE_FROM_A_CHAT",
                arguments={"channel": invocation.args["channel"], "ts": invocation.args["ts"]},
            )
        except ToolFailed as exc:
            if not exc.retryable and "message_not_found" in str(exc):
                return "the Slack message was already deleted"
            raise
        return "Slack message deleted"

    async def send_preview(ctx: AgentContext, args: ToolInput) -> dict[str, Any]:
        assert isinstance(args, SendSlackMessageArgs)
        return {"kind": "slack_message", "channel": args.channel.strip().lstrip("#"), "text": args.text, "thread_ts": args.thread_ts}

    return [
        ToolDefinition(
            name="search_slack_messages",
            description="Search the user's Slack workspace for messages (Slack search syntax), newest first.",
            kind=ToolKind.READ,
            scope=ToolScope.READ,
            category=ToolCategory.COMMUNICATION,
            input_model=SearchSlackArgs,
            handler=search_slack_messages,
            timeout_seconds=45,
            acl=require_slack,
        ),
        ToolDefinition(
            name="send_slack_message",
            description=(
                "Post a message to a Slack channel or DM as the rep (optionally as a thread reply). The rep approves "
                "the exact message first, so write complete, final text."
            ),
            kind=ToolKind.WRITE,
            scope=ToolScope.COMMUNICATION,
            category=ToolCategory.COMMUNICATION,
            input_model=SendSlackMessageArgs,
            handler=send_slack_message,
            timeout_seconds=45,
            acl=require_slack,
            preview=send_preview,
            undo_handler=delete_message,
        ),
    ]


def _message(match: dict[str, Any]) -> dict[str, Any]:
    link = match.get("permalink")
    return {
        "text": clip(match.get("text"), 800),
        "author": match.get("username") or match.get("user"),
        "channel": as_dict(match.get("channel")).get("name"),
        "date": _date(match.get("ts")),
        "link": link if isinstance(link, str) and link.startswith("https://") else None,
    }


def _date(ts: Any) -> str | None:
    try:
        return datetime.fromtimestamp(float(ts), UTC).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None
