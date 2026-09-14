"""Knowledge-base changes over data-pipeline's knowledge vault (shared by the workspace).

As decided for this build (2026-09-14), the agent may add public web pages, correct a document's
classification, have a document classified or indexed again, and delete documents, each only after
the rep approves. The tools need the KNOWLEDGE scope, which only the coordinator has: sub-agents can
read the knowledge base but never change it.

data-pipeline enforces the rules (viewers change nothing, only the person who added a document or a
workspace owner/admin deletes it, only public pages are fetched). The engine checks the same things
before the approval card, so the rep is never asked to approve something bound to be refused. Every
change records what it replaced: undo deletes a page the agent added and gives a classification its
previous values back. A deleted web page can be added again from its address; a deleted file is gone.
"""

from __future__ import annotations

import asyncio
import ipaddress
import time
from collections.abc import Awaitable, Callable
from typing import Annotated, Any
from urllib.parse import urlsplit

from pydantic import Field, StringConstraints

from app.core.context import AgentContext
from app.platform.data_pipeline import DataPipelineClient, DataPipelineError
from app.platform.workspace_client import WorkspaceDirectory
from app.tools.adapters.common import as_dict, as_list, clip, pipeline_failure, pipeline_write_failure, workspace_writer_required
from app.tools.adapters.knowledge import CATEGORIES, KnowledgeCategory, vault_entry
from app.tools.registry import ToolDefinition
from app.tools.types import (
    SourceLink,
    ToolAccessDenied,
    ToolCategory,
    ToolFailed,
    ToolInput,
    ToolInputError,
    ToolInvocation,
    ToolKind,
    ToolOutput,
    ToolScope,
    UndoInvocation,
    UndoPlan,
)

DocId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)]
Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]

_ADMIN_ROLES = frozenset({"OWNER", "ADMIN"})
# A document's classification: (argument name, data-pipeline field).
_CLASSIFICATION = (
    ("category", "category"),
    ("competitor", "target_competitor"),
    ("industry", "target_industry"),
    ("summary", "sales_summary"),
    ("tags", "sales_tags"),
)
_PROCESSING = "Parsing"
_SETTLE_POLL_SECONDS = 3.0


class AddWebPageArgs(ToolInput):
    url: str = Field(min_length=10, max_length=2000, description="The page's full address, starting with https:// or http://")
    title: str | None = Field(
        default=None, max_length=200, description="The name to show in the knowledge base; default: the name it already has, else the address"
    )
    category: KnowledgeCategory | None = Field(
        default=None, description="Leave out to keep the category a page already has, or to let the classifier decide for a new one"
    )
    competitor: str | None = Field(default=None, max_length=200, description="The competitor the page is about, if any")


class UpdateKnowledgeDocumentArgs(ToolInput):
    doc_id: DocId = Field(description="doc_id from list_knowledge_documents or search_knowledge_base")
    category: KnowledgeCategory | None = None
    competitor: str | None = Field(default=None, max_length=200, description="The competitor it is about; an empty string clears it")
    industry: str | None = Field(default=None, max_length=200, description="The industry it is for; an empty string clears it")
    summary: str | None = Field(default=None, max_length=2000, description="A short sales summary of the document")
    tags: list[Tag] | None = Field(default=None, max_length=8, description="Replaces all of its tags (at most 8)")


class KnowledgeDocumentArgs(ToolInput):
    doc_id: DocId = Field(description="doc_id from list_knowledge_documents or search_knowledge_base")


def knowledge_write_tools(
    client: DataPipelineClient,
    directory: WorkspaceDirectory,
    *,
    vault_link: str,
    settle_seconds: float = 40.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> list[ToolDefinition]:
    """``settle_seconds``: how long undoing a new page waits for data-pipeline to finish processing it."""
    writer = workspace_writer_required(directory, "the knowledge base")
    vault_link = vault_link.rstrip("/")

    def link(doc_id: str, name: str) -> tuple[SourceLink, ...]:
        return (SourceLink(title=name, url=f"{vault_link}?doc={doc_id}"),)

    # ------------------------------------------------------------------ lookups
    async def documents(ctx: AgentContext) -> list[dict[str, Any]]:
        try:
            return await client.list_documents(ctx.user_id, ctx.tenant_id, status=None)
        except DataPipelineError as exc:
            raise pipeline_failure(exc) from exc

    async def find_document(ctx: AgentContext, doc_id: str) -> dict[str, Any] | None:
        return next((doc for doc in await documents(ctx) if str(doc.get("doc_id")) == doc_id), None)

    async def document(ctx: AgentContext, doc_id: str) -> dict[str, Any]:
        found = await find_document(ctx, doc_id)
        if found is None:
            raise ToolInputError(f"the workspace's knowledge base has no document '{doc_id}'; look it up with list_knowledge_documents")
        return found

    def name_of(doc: dict[str, Any]) -> str:
        return str(doc.get("name") or doc.get("doc_id"))

    # ------------------------------------------------------------------ add a web page
    async def plan_page(ctx: AgentContext, args: AddWebPageArgs) -> tuple[str, dict[str, Any] | None, dict[str, Any]]:
        """(the address, the document already made from it if any, the title/category/competitor to send)."""
        address = public_address(args.url)
        existing = next((doc for doc in await documents(ctx) if as_dict(doc.get("metadata")).get("target_url") == address), None)
        # data-pipeline names a page without a title after its address and lets the classifier decide again, so a
        # refresh that doesn't say otherwise keeps the name and classification the document already has.
        kept = existing or {}
        fields = {
            "title": args.title or kept.get("name"),
            "category": args.category or (kept.get("category") if kept.get("category") in CATEGORIES else None),
            "competitor": args.competitor or kept.get("target_competitor"),
        }
        return address, existing, fields

    async def add_web_page(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, AddWebPageArgs)
        ctx = invocation.ctx
        address, existing, fields = await plan_page(ctx, args)
        try:
            added = await client.ingest_url(ctx.user_id, ctx.tenant_id, url=address, **fields)
        except DataPipelineError as exc:
            raise pipeline_write_failure(exc) from exc
        doc_id, name = str(added["doc_id"]), name_of(added)
        refreshed = existing is not None and str(existing.get("doc_id")) == doc_id
        return ToolOutput(
            data={"doc_id": doc_id, "name": name, "url": address, "status": added.get("status"), "refreshed": refreshed},
            summary=f"Web page '{name}' {'fetched again and refreshed in' if refreshed else 'added to'} the knowledge base; "
            "it is being indexed and becomes searchable in about a minute",
            ref_id=doc_id,
            sources=link(doc_id, name),
            # Refreshing replaced the page's earlier text, which can't be put back.
            undo=None if refreshed else UndoPlan(args={"doc_id": doc_id, "name": name}, label=f"Delete '{name}' from the knowledge base"),
        )

    async def page_preview(ctx: AgentContext, args: ToolInput) -> dict[str, Any]:
        assert isinstance(args, AddWebPageArgs)
        address, existing, fields = await plan_page(ctx, args)
        return {
            "kind": "knowledge_add_url",
            "url": address,
            "site": urlsplit(address).hostname,
            "title": fields["title"] or address,
            "category": fields["category"],
            "competitor": fields["competitor"],
            "existing": vault_entry(existing, ctx.user_id) if existing is not None else None,
        }

    async def delete_added_page(invocation: UndoInvocation) -> str:
        ctx = invocation.ctx
        doc_id, name = str(invocation.args["doc_id"]), str(invocation.args.get("name") or "the page")
        # A document deleted while data-pipeline is still processing it can leave its text and search index
        # behind (the job keeps writing), so an undo right after adding gives processing a moment to finish.
        deadline = time.monotonic() + settle_seconds
        found = await find_document(ctx, doc_id)
        while found is not None and found.get("status") == _PROCESSING and time.monotonic() < deadline:
            await sleep(_SETTLE_POLL_SECONDS)
            found = await find_document(ctx, doc_id)
        if found is None:
            return f"'{name}' was already gone from the knowledge base"
        try:
            removed = await client.delete_document(ctx.user_id, ctx.tenant_id, doc_id)
        except DataPipelineError as exc:
            raise pipeline_failure(exc) from exc
        return f"'{name}' deleted from the knowledge base" if removed else f"'{name}' was already gone from the knowledge base"

    # ------------------------------------------------------------------ correct the classification
    async def plan_update(
        ctx: AgentContext, args: UpdateKnowledgeDocumentArgs
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        """(the document, new values, the values they replace, the changes as shown to the rep)."""
        doc = await document(ctx, args.doc_id)
        changes: dict[str, Any] = {}
        previous: dict[str, Any] = {}
        shown: list[dict[str, Any]] = []
        for argument, field in _CLASSIFICATION:
            value = getattr(args, argument)
            if value is None:
                continue
            if field == "sales_tags":
                value, before = list(dict.fromkeys(value)), [str(tag) for tag in as_list(doc.get(field))]
            else:
                value, before = value.strip(), str(doc.get(field) or "")
            if value == before:
                continue
            changes[field], previous[field] = value, before
            shown.append({"field": argument, "before": before or None, "after": value or None})
        if not changes:
            raise ToolInputError(f"nothing to change: '{name_of(doc)}' already has these values")
        return doc, changes, previous, shown

    async def update_document(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, UpdateKnowledgeDocumentArgs)
        ctx = invocation.ctx
        doc, changes, previous, shown = await plan_update(ctx, args)
        name = name_of(doc)
        try:
            updated = await client.update_document_classification(ctx.user_id, ctx.tenant_id, args.doc_id, changes)
        except DataPipelineError as exc:
            raise pipeline_write_failure(exc) from exc
        if updated is None:
            raise ToolFailed(f"'{name}' was deleted before it could be changed")
        return ToolOutput(
            data={"doc_id": args.doc_id, "name": name, "changes": shown},
            summary=f"Updated '{name}': " + "; ".join(_describe(change) for change in shown),
            ref_id=args.doc_id,
            sources=link(args.doc_id, name),
            undo=UndoPlan(
                args={"doc_id": args.doc_id, "name": name, "fields": previous},
                label=f"Restore the previous {', '.join(change['field'] for change in shown)} of '{name}'",
            ),
        )

    async def update_preview(ctx: AgentContext, args: ToolInput) -> dict[str, Any]:
        assert isinstance(args, UpdateKnowledgeDocumentArgs)
        doc, _, _, shown = await plan_update(ctx, args)
        return {"kind": "knowledge_update", "doc_id": args.doc_id, "name": name_of(doc), "changes": shown}

    async def restore_classification(invocation: UndoInvocation) -> str:
        ctx = invocation.ctx
        name = str(invocation.args.get("name") or "the document")
        try:
            restored = await client.update_document_classification(
                ctx.user_id, ctx.tenant_id, str(invocation.args["doc_id"]), as_dict(invocation.args.get("fields"))
            )
        except DataPipelineError as exc:
            raise pipeline_failure(exc) from exc
        if restored is None:
            return f"'{name}' is no longer in the knowledge base, so there was nothing to restore"
        return f"restored the previous classification of '{name}'"

    # ------------------------------------------------------------------ classify again
    async def plan_reclassify(ctx: AgentContext, args: KnowledgeDocumentArgs) -> dict[str, Any]:
        doc = await document(ctx, args.doc_id)
        if doc.get("status") == _PROCESSING:
            raise ToolInputError(f"'{name_of(doc)}' is still being processed, and it is classified when that finishes")
        return doc

    async def reclassify_document(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, KnowledgeDocumentArgs)
        ctx = invocation.ctx
        doc = await plan_reclassify(ctx, args)
        name = name_of(doc)
        try:
            updated = await client.reclassify_document(ctx.user_id, ctx.tenant_id, args.doc_id)
        except DataPipelineError as exc:
            raise pipeline_write_failure(exc) from exc
        if updated is None:
            raise ToolFailed(f"'{name}' was deleted before it could be classified again")
        before = classification(doc)
        after = classification(updated)
        shown = [{"field": field, "before": before[field], "after": after[field]} for field in after if after[field] != before[field]]
        previous = {field: before_value(doc, field) for _, field in _CLASSIFICATION}
        return ToolOutput(
            data={"doc_id": args.doc_id, "name": name, "classification": after, "changes": shown},
            summary=f"Classified '{name}' again"
            + (": " + "; ".join(_describe(change) for change in shown) if shown else "; its classification stayed the same"),
            ref_id=args.doc_id,
            sources=link(args.doc_id, name),
            undo=UndoPlan(
                args={"doc_id": args.doc_id, "name": name, "fields": previous}, label=f"Restore the classification '{name}' had before"
            )
            if shown
            else None,
        )

    async def reclassify_preview(ctx: AgentContext, args: ToolInput) -> dict[str, Any]:
        assert isinstance(args, KnowledgeDocumentArgs)
        doc = await plan_reclassify(ctx, args)
        return {
            "kind": "knowledge_reclassify",
            "doc_id": args.doc_id,
            "name": name_of(doc),
            "current": classification(doc),
            "set_by_hand": doc.get("classifier_used") == "manual_user_override",
        }

    # ------------------------------------------------------------------ index again
    async def plan_reindex(ctx: AgentContext, args: KnowledgeDocumentArgs) -> dict[str, Any]:
        doc = await document(ctx, args.doc_id)
        if doc.get("status") == _PROCESSING:
            raise ToolInputError(f"'{name_of(doc)}' is already being processed")
        return doc

    async def reindex_document(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, KnowledgeDocumentArgs)
        ctx = invocation.ctx
        doc = await plan_reindex(ctx, args)
        name = name_of(doc)
        try:
            updated = await client.reindex_document(ctx.user_id, ctx.tenant_id, args.doc_id)
        except DataPipelineError as exc:
            raise pipeline_write_failure(exc) from exc
        if updated is None:
            raise ToolFailed(f"'{name}' was deleted before it could be indexed again")
        return ToolOutput(
            data={"doc_id": args.doc_id, "name": name, "status": updated.get("status"), "previous_status": doc.get("status")},
            summary=f"'{name}' is being indexed again; it becomes searchable in about a minute",
            ref_id=args.doc_id,
            sources=link(args.doc_id, name),
        )

    async def reindex_preview(ctx: AgentContext, args: ToolInput) -> dict[str, Any]:
        assert isinstance(args, KnowledgeDocumentArgs)
        doc = await plan_reindex(ctx, args)
        entry = vault_entry(doc, ctx.user_id)
        return {"kind": "knowledge_reindex", **{key: entry.get(key) for key in ("doc_id", "name", "status", "chunks", "problem", "source")}}

    # ------------------------------------------------------------------ delete
    async def may_delete(ctx: AgentContext, args: ToolInput) -> None:
        assert isinstance(args, KnowledgeDocumentArgs)
        role = await directory.role_in(ctx.user_id, ctx.tenant_id)
        if role is None:
            raise ToolAccessDenied("you are no longer a member of this workspace")
        if role == "VIEWER":
            raise ToolAccessDenied("viewers can't change the knowledge base; ask a workspace owner or admin")
        if role in _ADMIN_ROLES:
            return
        doc = await find_document(ctx, args.doc_id)  # a missing document is reported by the preview
        if doc is not None and str(doc.get("user_id")) != str(ctx.user_id):
            raise ToolAccessDenied(
                f"only the person who added '{name_of(doc)}' or a workspace owner or admin can delete it"
            )

    def page_address(doc: dict[str, Any]) -> str | None:
        """The address a deleted document can be fetched again from (web pages only)."""
        url = as_dict(doc.get("metadata")).get("target_url")
        return str(url) if doc.get("source") == "URL_INGEST" and url else None

    async def plan_delete(ctx: AgentContext, args: KnowledgeDocumentArgs) -> dict[str, Any]:
        doc = await document(ctx, args.doc_id)
        if doc.get("status") == _PROCESSING:
            # Deleting mid-processing can leave its text and search index behind (see delete_added_page).
            raise ToolInputError(f"'{name_of(doc)}' is still being processed; it can be deleted once that finishes, usually within a minute")
        return doc

    async def delete_document(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, KnowledgeDocumentArgs)
        ctx = invocation.ctx
        doc = await plan_delete(ctx, args)
        name = name_of(doc)
        try:
            removed = await client.delete_document(ctx.user_id, ctx.tenant_id, args.doc_id)
        except DataPipelineError as exc:
            raise pipeline_write_failure(exc) from exc
        if not removed:
            return ToolOutput(data={"doc_id": args.doc_id, "name": name, "deleted": False}, summary=f"'{name}' was already gone from the knowledge base")
        address = page_address(doc)
        undo = None
        if address:
            category = doc.get("category") if doc.get("category") in CATEGORIES else None
            undo = UndoPlan(
                args={"url": address, "title": name, "category": category, "competitor": doc.get("target_competitor")},
                label=f"Add the web page '{name}' back from {address}",
            )
        return ToolOutput(
            data={"doc_id": args.doc_id, "name": name, "deleted": True},
            summary=f"Deleted '{name}' from the knowledge base" + ("" if undo else "; it can't be restored"),
            ref_id=args.doc_id,
            undo=undo,
        )

    async def delete_preview(ctx: AgentContext, args: ToolInput) -> dict[str, Any]:
        assert isinstance(args, KnowledgeDocumentArgs)
        doc = await plan_delete(ctx, args)
        entry = vault_entry(doc, ctx.user_id)
        return {
            "kind": "knowledge_delete",
            **{key: entry.get(key) for key in ("doc_id", "name", "type", "status", "category", "chunks", "source", "url", "added_by_me")},
            "restorable": page_address(doc) is not None,
        }

    async def add_page_back(invocation: UndoInvocation) -> str:
        ctx = invocation.ctx
        undo = invocation.args
        try:
            # Adding an address that is already there refreshes it, so a retried undo can't add it twice.
            added = await client.ingest_url(
                ctx.user_id,
                ctx.tenant_id,
                url=str(undo["url"]),
                title=undo.get("title"),
                category=undo.get("category"),
                competitor=undo.get("competitor"),
            )
        except DataPipelineError as exc:
            raise pipeline_failure(exc) from exc
        return f"added the web page '{name_of(added)}' back from {undo['url']} (it is being indexed)"

    common = {"kind": ToolKind.WRITE, "scope": ToolScope.KNOWLEDGE, "category": ToolCategory.ACTION, "acl": writer, "timeout_seconds": 60}
    return [
        ToolDefinition(
            name="add_web_page_to_knowledge_base",
            description=(
                "Add a public web page (a competitor's pricing page, a product announcement, an analyst article) to the "
                "workspace knowledge base so it can be searched. It is fetched and indexed in the background. Adding an "
                "address that is already there fetches it again and refreshes it."
            ),
            input_model=AddWebPageArgs,
            handler=add_web_page,
            preview=page_preview,
            undo_handler=delete_added_page,
            **(common | {"timeout_seconds": 90}),  # the page fetch, or an undo waiting for processing to finish
        ),
        ToolDefinition(
            name="update_knowledge_document",
            description=(
                "Correct a knowledge-base document's category, competitor, industry, sales summary or tags. Only the "
                "fields you pass change."
            ),
            input_model=UpdateKnowledgeDocumentArgs,
            handler=update_document,
            preview=update_preview,
            undo_handler=restore_classification,
            **common,
        ),
        ToolDefinition(
            name="reclassify_knowledge_document",
            description=(
                "Have the classifier read a knowledge-base document again and replace its category, competitor, "
                "industry, summary and tags, including values set by hand."
            ),
            input_model=KnowledgeDocumentArgs,
            handler=reclassify_document,
            preview=reclassify_preview,
            undo_handler=restore_classification,
            **(common | {"timeout_seconds": 150}),
        ),
        ToolDefinition(
            name="reindex_knowledge_document",
            description=(
                "Rebuild a knowledge-base document's search index from its stored content: for a document in Error, or "
                "one that search doesn't find. To get a web page's current content, add its address again instead."
            ),
            input_model=KnowledgeDocumentArgs,
            handler=reindex_document,
            preview=reindex_preview,
            **common,
        ),
        ToolDefinition(
            name="delete_knowledge_document",
            description=(
                "Delete a document from the workspace knowledge base, for everyone. Only the person who added it or a "
                "workspace owner or admin may. A deleted file can't be restored; a web page can be added again."
            ),
            input_model=KnowledgeDocumentArgs,
            handler=delete_document,
            preview=delete_preview,
            undo_handler=add_page_back,
            irreversible=True,  # a deleted file is gone: never without a person's approval
            **(common | {"acl": may_delete}),
        ),
    ]


def public_address(url: str) -> str:
    """The address, if it can be a public web page. data-pipeline makes the final check on every connection;
    this one catches the obvious cases before the rep is asked to approve a fetch that would be refused."""
    address = url.strip()
    try:
        parts = urlsplit(address)
        host = (parts.hostname or "").lower()
        _ = parts.port  # an unusable port raises here
    except ValueError as exc:
        raise ToolInputError(f"'{clip(address, 200)}' is not a usable web address") from exc
    if parts.scheme.lower() not in ("http", "https") or not host or any(char.isspace() for char in address):
        raise ToolInputError("give the page's full address, starting with https:// or http://")
    if parts.username or parts.password:
        raise ToolInputError("an address with a user name or password can't be added")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        internal = host == "localhost" or host.endswith((".localhost", ".local", ".internal")) or "." not in host
    else:
        internal = not (getattr(ip, "ipv4_mapped", None) or ip).is_global
    if internal:
        raise ToolInputError(f"{host} is not on the public internet; only public web pages can be added to the knowledge base")
    return address


def classification(doc: dict[str, Any]) -> dict[str, Any]:
    return {argument: doc.get(field) or ([] if field == "sales_tags" else None) for argument, field in _CLASSIFICATION}


def before_value(doc: dict[str, Any], field: str) -> Any:
    """A field's current value as data-pipeline takes it back (an empty string clears a text field)."""
    value = doc.get(field)
    if field == "sales_tags":
        return [str(tag) for tag in as_list(value)]
    return str(value) if value else ""


def _describe(change: dict[str, Any]) -> str:
    field, before, after = change["field"], change["before"], change["after"]
    if field == "summary":
        return "summary rewritten" if after else "summary cleared"
    if field == "tags":
        return f"tags: {', '.join(after or []) or 'none'}"
    return f"{field} {before or 'none'} → {after or 'none'}"
