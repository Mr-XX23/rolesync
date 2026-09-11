"""Notion over Composio: search and read pages, create a page (undo: move it to the trash)."""

from __future__ import annotations

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
    ToolInput,
    ToolInvocation,
    ToolKind,
    ToolOutput,
    ToolScope,
    UndoInvocation,
    UndoPlan,
)

_PAGE_TEXT_LIMIT = 12_000


class SearchNotionArgs(ToolInput):
    query: str = Field(min_length=1, max_length=200, description="Words in the page title")
    max_results: int = Field(default=10, ge=1, le=25)


class ReadNotionPageArgs(ToolInput):
    page_id: str = Field(min_length=32, max_length=36, description="page id from search_notion")


class CreateNotionPageArgs(ToolInput):
    parent_page_id: str = Field(
        min_length=32, max_length=36, description="The page (or database) to create it under: a page_id from search_notion"
    )
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(default="", max_length=50_000, description="The page body in Markdown")


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

    async def create_notion_page(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, CreateNotionPageArgs)
        arguments: dict[str, Any] = {"parent_id": args.parent_page_id, "title": args.title}
        if args.content.strip():
            arguments["markdown"] = args.content
        data = await run_connector_write(
            connector, user_id=invocation.ctx.user_id, slug="NOTION_CREATE_NOTION_PAGE", arguments=arguments
        )
        page = first_dict(data, "response_data", "page", "data")
        page_id = str(page.get("id") or "") or None
        url = page.get("url") if isinstance(page.get("url"), str) else None
        return ToolOutput(
            data={"page_id": page_id, "title": args.title, "url": url},
            summary=f"Notion page '{args.title}' created",
            ref_id=page_id,
            sources=(SourceLink(title=args.title, url=url),) if url and url.startswith("https://") else (),
            undo=UndoPlan(args={"page_id": page_id}, label=f"Move the Notion page '{args.title}' to the trash")
            if page_id
            else None,
        )

    async def archive_page(invocation: UndoInvocation) -> str:
        page_id = str(invocation.args["page_id"])
        await run_connector_undo(
            connector,
            user_id=invocation.ctx.user_id,
            slug="NOTION_ARCHIVE_NOTION_PAGE",
            arguments={"page_id": page_id, "archive": True},
        )
        return f"Notion page {page_id} moved to the trash"

    async def create_preview(ctx: AgentContext, args: ToolInput) -> dict[str, Any]:
        assert isinstance(args, CreateNotionPageArgs)
        return {"kind": "notion_page", "parent_page_id": args.parent_page_id, "title": args.title, "content": args.content}

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
        ToolDefinition(
            name="create_notion_page",
            description=(
                "Create a Notion page with a title and Markdown content under an existing page the rep can access "
                "(find the parent with search_notion). The rep approves it first."
            ),
            kind=ToolKind.WRITE,
            scope=ToolScope.COMMUNICATION,
            category=ToolCategory.ACTION,
            input_model=CreateNotionPageArgs,
            handler=create_notion_page,
            timeout_seconds=60,
            acl=require_notion,
            preview=create_preview,
            undo_handler=archive_page,
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
