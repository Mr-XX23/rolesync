"""Slack reads over Composio."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import Field

from app.platform.composio_client import ConnectorClient
from app.tools.adapters.common import as_dict, as_list, clip, connection_required, plural, run_connector
from app.tools.registry import ToolDefinition
from app.tools.types import SourceLink, ToolCategory, ToolInput, ToolInvocation, ToolKind, ToolOutput, ToolScope


class SearchSlackArgs(ToolInput):
    query: str = Field(
        min_length=1,
        max_length=300,
        description="Slack search, e.g. 'acme renewal', 'in:#sales acme', 'from:@jane after:2026-01-01'",
    )
    max_results: int = Field(default=10, ge=1, le=25)


def slack_tools(connector: ConnectorClient) -> list[ToolDefinition]:
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
            acl=connection_required(connector, "slack", "Slack"),
        )
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
