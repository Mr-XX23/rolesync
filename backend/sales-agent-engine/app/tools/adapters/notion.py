"""Notion reads over Composio."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from app.platform.composio_client import ConnectorClient
from app.tools.adapters.common import as_dict, as_list, clip, connection_required, plural, run_connector
from app.tools.registry import ToolDefinition
from app.tools.types import SourceLink, ToolCategory, ToolInput, ToolInvocation, ToolKind, ToolOutput, ToolScope

_PAGE_TEXT_LIMIT = 12_000


class SearchNotionArgs(ToolInput):
    query: str = Field(min_length=1, max_length=200, description="Words in the page title")
    max_results: int = Field(default=10, ge=1, le=25)


class ReadNotionPageArgs(ToolInput):
    page_id: str = Field(min_length=32, max_length=36, description="page id from search_notion")


def notion_tools(connector: ConnectorClient) -> list[ToolDefinition]:
    require_notion = connection_required(connector, "notion", "Notion")

    async def search_notion(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, SearchNotionArgs)
        data = await run_connector(
            connector,
            user_id=invocation.ctx.user_id,
            slug="NOTION_SEARCH_NOTION_PAGE",
            arguments={"query": args.query, "page_size": args.max_results},
        )
        pages = [
            {
                "page_id": item.get("id"),
                "title": _title(item),
                "url": item.get("url"),
                "last_edited": item.get("last_edited_time"),
            }
            for item in (as_dict(result) for result in as_list(data.get("results")))
            if item.get("id") and not item.get("archived") and not item.get("in_trash")
        ]
        return ToolOutput(
            data={"pages": pages},
            summary=f"{plural(len(pages), 'Notion page')} matching '{args.query}'",
            sources=_links(pages),
        )

    async def read_notion_page(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, ReadNotionPageArgs)
        data = await run_connector(
            connector,
            user_id=invocation.ctx.user_id,
            slug="NOTION_GET_PAGE_MARKDOWN",
            arguments={"page_id": args.page_id},
        )
        markdown = data.get("markdown") if isinstance(data.get("markdown"), str) else ""
        text = clip(markdown, _PAGE_TEXT_LIMIT)
        return ToolOutput(
            data={"page_id": args.page_id, "markdown": text, "truncated": len(text) < len(markdown.strip()) or bool(data.get("truncated"))},
            summary=f"Notion page {args.page_id}: {plural(len(markdown), 'character')}",
        )

    return [
        ToolDefinition(
            name="search_notion",
            description="Find pages in the user's Notion workspace by title.",
            kind=ToolKind.READ,
            scope=ToolScope.READ,
            category=ToolCategory.KNOWLEDGE,
            input_model=SearchNotionArgs,
            handler=search_notion,
            timeout_seconds=45,
            acl=require_notion,
        ),
        ToolDefinition(
            name="read_notion_page",
            description="Read one Notion page (from search_notion) as Markdown.",
            kind=ToolKind.READ,
            scope=ToolScope.READ,
            category=ToolCategory.KNOWLEDGE,
            input_model=ReadNotionPageArgs,
            handler=read_notion_page,
            timeout_seconds=45,
            acl=require_notion,
        ),
    ]


def _title(item: dict[str, Any]) -> str:
    if item.get("object") == "database":
        return _plain(item.get("title")) or "(untitled database)"
    for prop in as_dict(item.get("properties")).values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            return _plain(prop.get("title")) or "(untitled)"
    return "(untitled)"


def _plain(rich_text: Any) -> str:
    return "".join(str(as_dict(part).get("plain_text") or "") for part in as_list(rich_text)).strip()


def _links(pages: list[dict[str, Any]]) -> tuple[SourceLink, ...]:
    return tuple(
        SourceLink(title=page["title"], url=page["url"])
        for page in pages[:5]
        if isinstance(page.get("url"), str) and page["url"].startswith("https://")
    )
