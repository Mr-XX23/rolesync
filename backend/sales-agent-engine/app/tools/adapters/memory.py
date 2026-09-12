"""The agent's memory tools: facts that carry over between conversations.

- about the rep (REP memory): private to that rep
- about a customer company (ACCOUNT memory) or a deal (DEAL memory): shared by the workspace

As decided for this build, the agent saves memories on its own, without an approval card, and
the rep reviews and deletes them in the app. Viewers of a workspace can read its shared memory
but not change it. Every change goes through ``MemoryStore.update`` (optimistic versioning), so
two agents remembering things about the same customer at once never lose each other's facts.

``read_offloaded_result`` reads back a tool result that was too large to keep in the conversation.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.context.locks import MemoryBusy
from app.context.stores import BlobStore, MemoryStore, account_key, add_fact, facts_of, remove_fact
from app.core.clock import utcnow
from app.core.context import AgentContext
from app.core.enums import MemoryScope
from app.platform.workspace_client import DealsClient, WorkspaceDirectory, WorkspaceServiceError
from app.tools.registry import ToolDefinition
from app.tools.types import (
    ToolAccessDenied,
    ToolCategory,
    ToolFailed,
    ToolInput,
    ToolInputError,
    ToolInvocation,
    ToolKind,
    ToolOutput,
    ToolScope,
)

About = Literal["rep", "account", "deal"]


class _Target(ToolInput):
    company: str | None = Field(default=None, min_length=1, max_length=200, description="The customer company (about=account)")
    deal_id: UUID | None = Field(default=None, description="The deal (about=deal), from search_deals")

    def _require_target(self, about: str) -> None:
        if about == "account" and not (self.company and self.company.strip()):
            raise ValueError("company is required when about is 'account'")
        if about == "deal" and self.deal_id is None:
            raise ValueError("deal_id is required when about is 'deal'")


class RememberArgs(_Target):
    about: About = Field(
        description="rep: the rep you work for (private to them); account: a customer company; deal: one deal "
        "(account and deal memories are shared with the workspace)"
    )
    fact: str = Field(min_length=3, max_length=500, description="One durable fact, worded so it makes sense on its own later")

    @model_validator(mode="after")
    def _target(self) -> RememberArgs:
        self._require_target(self.about)
        return self


class RecallArgs(_Target):
    about: Literal["rep", "account", "deal", "accounts"] = Field(
        description="What to recall; 'accounts' lists the customer companies with saved memories"
    )
    query: str | None = Field(default=None, max_length=200, description="Only facts (or accounts) mentioning these words")

    @model_validator(mode="after")
    def _target(self) -> RecallArgs:
        self._require_target(self.about)
        return self


class ForgetArgs(_Target):
    about: About
    fact_id: str = Field(pattern=r"^f_[0-9a-f]{12}$", description="The id of the fact to forget (from recall)")

    @model_validator(mode="after")
    def _target(self) -> ForgetArgs:
        self._require_target(self.about)
        return self


class ReadOffloadedArgs(ToolInput):
    ref: UUID = Field(description="The offloaded.ref of a tool result")
    offset: int = Field(default=0, ge=0, description="Start reading at this character")
    length: int = Field(default=8_000, ge=500, le=16_000)
    find: str | None = Field(default=None, min_length=2, max_length=100, description="Return the passages around this text instead")


def memory_tools(
    store: MemoryStore,
    blobs: BlobStore,
    directory: WorkspaceDirectory,
    deals: DealsClient | None = None,
    *,
    facts_per_key: int = 100,
) -> list[ToolDefinition]:
    async def target(ctx: AgentContext, args: _Target, about: str, *, writing: bool) -> tuple[MemoryScope, str, str | None]:
        """(scope, key, display name) for what a memory is about, checking the caller may use it."""
        if about == "rep":
            return MemoryScope.REP, str(ctx.user_id), None
        if writing:
            role = await directory.role_in(ctx.user_id, ctx.tenant_id)
            if role is None:
                raise ToolAccessDenied("you are no longer a member of this workspace")
            if role == "VIEWER":
                raise ToolAccessDenied("viewers can't change the workspace's shared memory")
        if about == "account":
            company = (args.company or "").strip()
            try:
                return MemoryScope.ACCOUNT, account_key(company), company
            except ValueError as exc:
                raise ToolInputError(str(exc)) from exc
        assert args.deal_id is not None
        title = None
        if deals is not None:
            try:
                deal = await deals.get(ctx.user_id, ctx.tenant_id, args.deal_id)
            except WorkspaceServiceError as exc:
                raise ToolFailed(str(exc), retryable=exc.retryable) from exc
            if deal is None:
                raise ToolInputError(f"there is no deal {args.deal_id} in this workspace")
            title = str(deal.get("title") or "") or None
        return MemoryScope.DEAL, str(args.deal_id), title

    async def remember(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, RememberArgs)
        ctx = invocation.ctx
        scope, key, name = await target(ctx, args, args.about, writing=True)
        saved: dict[str, Any] = {}

        def mutate(content: dict[str, Any]) -> dict[str, Any] | None:
            updated, fact = add_fact(
                content, args.fact, saved_by=ctx.user_id, session_id=ctx.session_id, now=utcnow(), limit=facts_per_key, name=name
            )
            saved["fact"] = fact
            return updated

        try:
            record = await store.update(tenant_id=ctx.tenant_id, scope=scope, key=key, mutate=mutate, written_by=ctx.user_id)
        except MemoryBusy as exc:
            raise ToolFailed(str(exc), retryable=True) from exc
        fact = saved["fact"]
        subject = _subject(args.about, name, key)
        return ToolOutput(
            data={
                "about": args.about,
                "fact_id": fact["id"],
                "fact": fact["text"],
                "facts_known": len(facts_of(record.content if record else None)),
            },
            summary=f"Remembered about {subject}: {fact['text']}",
        )

    async def recall(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, RecallArgs)
        ctx = invocation.ctx
        words = _words(args.query)
        if args.about == "accounts":
            records = await store.list_latest(tenant_id=ctx.tenant_id, scope=MemoryScope.ACCOUNT)
            accounts = [
                {
                    "company": record.content.get("name") or record.key,
                    "facts": len(facts_of(record.content)),
                    "updated_at": _iso(record.updated_at),
                }
                for record in records
                if facts_of(record.content)
                and (not words or all(word in f"{record.content.get('name', '')} {record.key}".lower() for word in words))
            ][:25]
            return ToolOutput(data={"accounts": accounts}, summary=f"{len(accounts)} customer compan{'y' if len(accounts) == 1 else 'ies'} with memories")

        scope, key, name = await target(ctx, args, args.about, writing=False)
        record = await store.latest(tenant_id=ctx.tenant_id, scope=scope, key=key)
        facts = [
            {"id": fact["id"], "fact": fact.get("text"), "saved_at": fact.get("saved_at")}
            for fact in reversed(facts_of(record.content if record else None))  # newest first
            if not words or all(word in str(fact.get("text", "")).lower() for word in words)
        ][:50]
        subject = _subject(args.about, name or (record.content.get("name") if record else None), key)
        return ToolOutput(
            data={"about": args.about, "subject": subject, "facts": facts},
            summary=f"{len(facts)} remembered fact{'s' if len(facts) != 1 else ''} about {subject}",
        )

    async def forget(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, ForgetArgs)
        ctx = invocation.ctx
        scope, key, name = await target(ctx, args, args.about, writing=True)
        removed: dict[str, Any] = {}

        def mutate(content: dict[str, Any]) -> dict[str, Any] | None:
            removed.update(fact=next((fact for fact in facts_of(content) if fact.get("id") == args.fact_id), None))
            return remove_fact(content, args.fact_id)

        try:
            await store.update(tenant_id=ctx.tenant_id, scope=scope, key=key, mutate=mutate, written_by=ctx.user_id)
        except MemoryBusy as exc:
            raise ToolFailed(str(exc), retryable=True) from exc
        if removed.get("fact") is None:
            raise ToolInputError(f"there is no remembered fact {args.fact_id} about {_subject(args.about, name, key)}")
        return ToolOutput(
            data={"about": args.about, "fact_id": args.fact_id},
            summary=f"Forgot about {_subject(args.about, name, key)}: {removed['fact'].get('text')}",
        )

    async def read_offloaded_result(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, ReadOffloadedArgs)
        ctx = invocation.ctx
        blob = await blobs.get(tenant_id=ctx.tenant_id, session_id=ctx.session_id, ref=args.ref)
        if blob is None:
            raise ToolInputError("there is no stored result with that ref in this conversation")
        content = blob.content
        if args.find:
            needle = args.find.lower()
            lowered = content.lower()
            passages: list[str] = []
            start = 0
            while len(passages) < 5 and (position := lowered.find(needle, start)) >= 0:
                passages.append(content[max(0, position - 600) : position + len(needle) + 600])
                start = position + len(needle)
            return ToolOutput(
                data={"tool": blob.tool, "chars": blob.chars, "find": args.find, "passages": passages},
                summary=f"{len(passages)} passage{'s' if len(passages) != 1 else ''} mentioning '{args.find}' in the stored {blob.tool} result",
            )
        chunk = content[args.offset : args.offset + args.length]
        end = args.offset + len(chunk)
        return ToolOutput(
            data={"tool": blob.tool, "chars": blob.chars, "offset": args.offset, "text": chunk, "next_offset": end if end < blob.chars else None},
            summary=f"Characters {args.offset}–{end} of {blob.chars} from the stored {blob.tool} result",
        )

    return [
        ToolDefinition(
            name="remember",
            description=(
                "Save a durable fact for future conversations: about the rep you work for (preferences such as tone, "
                "sign-off, meeting length), about a customer company (contacts and roles, needs, objections, budget, "
                "timeline, competitors, what was quoted) or about a deal. Saved without asking; the rep can review and "
                "delete memories. Never save passwords, payment details or other secrets."
            ),
            kind=ToolKind.MEMORY,
            scope=ToolScope.MEMORY,
            category=ToolCategory.KNOWLEDGE,
            input_model=RememberArgs,
            handler=remember,
            timeout_seconds=20,
        ),
        ToolDefinition(
            name="recall",
            description=(
                "Recall saved facts about the rep, a customer company or a deal, or list the customer companies with "
                "saved memories. Recall a company before working on it."
            ),
            kind=ToolKind.READ,
            scope=ToolScope.READ,
            category=ToolCategory.KNOWLEDGE,
            input_model=RecallArgs,
            handler=recall,
            timeout_seconds=20,
        ),
        ToolDefinition(
            name="forget",
            description="Forget one saved fact (by its id from recall), e.g. when the rep says it is wrong or outdated.",
            kind=ToolKind.MEMORY,
            scope=ToolScope.MEMORY,
            category=ToolCategory.KNOWLEDGE,
            input_model=ForgetArgs,
            handler=forget,
            timeout_seconds=20,
        ),
        ToolDefinition(
            name="read_offloaded_result",
            description=(
                "Read a tool result that was too long to keep in the conversation (its offloaded.ref): a slice of it, "
                "or the passages around some text."
            ),
            kind=ToolKind.READ,
            scope=ToolScope.READ,
            category=ToolCategory.KNOWLEDGE,
            input_model=ReadOffloadedArgs,
            handler=read_offloaded_result,
            timeout_seconds=20,
        ),
    ]


def _subject(about: str, name: str | None, key: str) -> str:
    if about == "rep":
        return "the rep"
    if about == "deal":
        return f"the deal '{name}'" if name else f"deal {key}"
    return name or key


def _words(query: str | None) -> list[str]:
    return [word for word in re.findall(r"[\w'-]+", (query or "").lower()) if len(word) > 1]


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment else None
