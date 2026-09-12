"""Deal tools over workspace-service, where deals live (decided for this build).

Deals are shared by the workspace. Creating or changing one is a gated write (the rep approves
the exact change) and can be undone. workspace-service versions every deal: a change is made
against the version it was read at, and when someone else changed the deal in between, the
tool re-reads and re-applies its change (a merge) rather than overwriting theirs. Undo follows
the same rule: it only puts back fields nobody has touched since.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID, uuid5

from pydantic import Field, StringConstraints

from app.context.stores import account_key
from app.core.context import AgentContext
from app.platform.workspace_client import DealsClient, WorkspaceDirectory, WorkspaceServiceError
from app.tools.adapters.common import plural, workspace_writer_required
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
    ToolOutcomeUnknown,
    ToolOutput,
    ToolScope,
    UndoInvocation,
    UndoPlan,
)

Stage = Literal["PROSPECTING", "QUALIFIED", "PROPOSAL", "NEGOTIATION", "WON", "LOST"]
CLOSED = frozenset({"WON", "LOST"})
EmailAddress = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=320)]
_NAMESPACE = UUID("7a3e6d4c-1f0b-4c9e-8d2a-5b6f7e8d9c01")
_FIELDS = ("title", "company", "stage", "amount", "currency", "expected_close_date", "next_step", "notes")
_CONFLICT_RETRIES = 3


class ContactArgs(ToolInput):
    name: str = Field(min_length=1, max_length=150)
    email: EmailAddress | None = None
    role: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=40)


class SearchDealsArgs(ToolInput):
    query: str | None = Field(default=None, max_length=200, description="Words in the company or deal title")
    stage: Stage | None = None
    mine: bool = Field(default=False, description="Only the rep's own deals")
    max_results: int = Field(default=10, ge=1, le=25)


class CreateDealArgs(ToolInput):
    title: str = Field(min_length=3, max_length=200, description="e.g. 'Acme - 50 Pro seats'")
    company: str = Field(min_length=1, max_length=200)
    stage: Stage = "PROSPECTING"
    amount: float | None = Field(default=None, ge=0, le=10_000_000_000_000)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    expected_close_date: date | None = None
    next_step: str | None = Field(default=None, max_length=500)
    contacts: list[ContactArgs] = Field(default_factory=list, max_length=20)
    notes: str | None = Field(default=None, max_length=5_000)


class UpdateDealArgs(ToolInput):
    deal_id: UUID = Field(description="From search_deals")
    title: str | None = Field(default=None, min_length=3, max_length=200)
    company: str | None = Field(default=None, min_length=1, max_length=200)
    stage: Stage | None = None
    amount: float | None = Field(default=None, ge=0, le=10_000_000_000_000)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    expected_close_date: date | None = None
    next_step: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=5_000)
    add_contacts: list[ContactArgs] = Field(default_factory=list, max_length=20)


def deal_tools(deals: DealsClient, directory: WorkspaceDirectory) -> list[ToolDefinition]:
    writer = workspace_writer_required(directory, "the workspace's deals")

    async def search_deals(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, SearchDealsArgs)
        ctx = invocation.ctx
        try:
            found = await deals.list(ctx.user_id, ctx.tenant_id, query=args.query, stage=args.stage, mine=args.mine, limit=args.max_results)
        except WorkspaceServiceError as exc:
            raise ToolFailed(str(exc), retryable=exc.retryable) from exc
        items = [_brief(deal) for deal in found[: args.max_results]]
        what = f" matching '{args.query}'" if args.query else ""
        return ToolOutput(data={"deals": items}, summary=f"{plural(len(items), 'deal')}{what}")

    # ------------------------------------------------------------------ create
    async def open_deals_for(ctx: AgentContext, company: str) -> list[dict[str, Any]]:
        try:
            key = account_key(company)
            found = await deals.list(ctx.user_id, ctx.tenant_id, query=key.split("-")[0], limit=50)
        except (WorkspaceServiceError, ValueError):
            return []
        return [deal for deal in found if deal.get("stage") not in CLOSED and account_key(str(deal.get("company") or "")) == key]

    async def create_deal(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, CreateDealArgs)
        ctx = invocation.ctx
        deal_id = uuid5(_NAMESPACE, f"{ctx.session_id}:{invocation.call_id}")
        body = {
            "title": args.title,
            "company": args.company,
            "stage": args.stage,
            "amount": args.amount,
            "currency": args.currency,
            "expected_close_date": args.expected_close_date.isoformat() if args.expected_close_date else None,
            "next_step": args.next_step,
            "notes": args.notes,
            "contacts": [contact.model_dump(exclude_none=True) for contact in args.contacts],
            "quotes": [],
            "source": "AGENT",
        }
        try:
            created = await deals.put(ctx.user_id, ctx.tenant_id, deal_id, body)
        except WorkspaceServiceError as exc:
            raise _write_failure(exc) from exc
        return ToolOutput(
            data=_brief(created),
            summary=f"Deal '{args.title}' created for {args.company} ({args.stage}{_money(created)})",
            ref_id=str(deal_id),
            sources=(SourceLink(title=args.title, url=f"/salesman/deals?deal={deal_id}"),),
            undo=UndoPlan(
                args={"deal_id": str(deal_id), "snapshot": {field: created.get(field) for field in _FIELDS}},
                label=f"Delete the new deal '{args.title}'",
            ),
        )

    async def create_preview(ctx: AgentContext, args: ToolInput) -> dict[str, Any]:
        assert isinstance(args, CreateDealArgs)
        existing = await open_deals_for(ctx, args.company)
        return {
            "kind": "deal_create",
            "deal": args.model_dump(mode="json"),
            "warnings": [f"There is already an open deal for {deal.get('company')}: '{deal.get('title')}' ({deal.get('stage')})" for deal in existing[:3]],
        }

    async def delete_created(invocation: UndoInvocation) -> str:
        ctx = invocation.ctx
        deal_id = UUID(str(invocation.args["deal_id"]))
        snapshot = dict(invocation.args.get("snapshot") or {})
        for _ in range(_CONFLICT_RETRIES):
            try:
                current = await deals.get(ctx.user_id, ctx.tenant_id, deal_id)
            except WorkspaceServiceError as exc:
                raise ToolFailed(str(exc), retryable=exc.retryable) from exc
            if current is None:
                return "the deal was already deleted"
            changed = [field for field in _FIELDS if _normalize(current.get(field)) != _normalize(snapshot.get(field))]
            if changed or current.get("quotes"):
                what = ", ".join(changed) if changed else "quotes linked to it"
                raise ToolFailed(f"the deal was changed after it was created ({what}), so it was kept")
            try:
                await deals.delete(ctx.user_id, ctx.tenant_id, deal_id, expected_version=int(current["version"]))
                return f"deleted the deal '{current.get('title')}'"
            except WorkspaceServiceError as exc:
                if exc.status != 409:
                    raise ToolFailed(str(exc), retryable=exc.retryable) from exc
        raise ToolFailed("the deal kept changing while it was being deleted", retryable=True)

    # ------------------------------------------------------------------ update
    def plan_update(args: UpdateDealArgs, current: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        """(new PUT body, field changes, contacts added) for ``args`` applied to ``current``."""
        wanted = args.model_dump(mode="json", exclude={"deal_id", "add_contacts"}, exclude_none=True)
        changes = [
            {"field": field, "before": current.get(field), "after": value}
            for field, value in wanted.items()
            if _normalize(current.get(field)) != _normalize(value)
        ]
        contacts = list(current.get("contacts") or [])
        known = {_contact_key(contact) for contact in contacts}
        added = []
        for contact in args.add_contacts:
            entry = contact.model_dump(exclude_none=True)
            if _contact_key(entry) not in known:
                contacts.append(entry)
                known.add(_contact_key(entry))
                added.append(entry)
        body = _body(current) | {change["field"]: change["after"] for change in changes} | {"contacts": contacts}
        return body, changes, added

    async def update_deal(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, UpdateDealArgs)
        ctx = invocation.ctx
        for _ in range(_CONFLICT_RETRIES):
            current = await _get_existing(deals, ctx, args.deal_id)
            body, changes, added = plan_update(args, current)
            if not changes and not added:
                raise ToolInputError("nothing to change: the deal already has these values")
            try:
                saved = await deals.put(ctx.user_id, ctx.tenant_id, args.deal_id, body | {"expected_version": current["version"]})
            except WorkspaceServiceError as exc:
                if exc.status == 409:
                    continue  # someone else changed it: re-read and apply the change to their version
                raise _write_failure(exc) from exc
            described = [f"{change['field'].replace('_', ' ')} {_show(change['before'])} → {_show(change['after'])}" for change in changes]
            if added:
                described.append(f"added {plural(len(added), 'contact')}")
            return ToolOutput(
                data={"deal": _brief(saved), "changes": changes, "contacts_added": added},
                summary=f"Deal '{saved.get('title')}' updated: " + "; ".join(described),
                ref_id=str(args.deal_id),
                sources=(SourceLink(title=str(saved.get("title") or "the deal"), url=f"/salesman/deals?deal={args.deal_id}"),),
                undo=UndoPlan(
                    args={
                        "deal_id": str(args.deal_id),
                        "restore": {change["field"]: change["before"] for change in changes},
                        "applied": {change["field"]: change["after"] for change in changes},
                        "contacts_added": added,
                    },
                    label=f"Restore the previous values of the deal '{current.get('title')}'",
                ),
            )
        raise ToolFailed("the deal kept changing while this update was being saved; try again", retryable=False)

    async def update_preview(ctx: AgentContext, args: ToolInput) -> dict[str, Any]:
        assert isinstance(args, UpdateDealArgs)
        current = await _get_existing(deals, ctx, args.deal_id)
        _, changes, added = plan_update(args, current)
        if not changes and not added:
            raise ToolInputError("nothing to change: the deal already has these values")
        return {
            "kind": "deal_update",
            "deal_id": str(args.deal_id),
            "title": current.get("title"),
            "company": current.get("company"),
            "changes": changes,
            "contacts_added": added,
        }

    async def restore_deal(invocation: UndoInvocation) -> str:
        ctx = invocation.ctx
        deal_id = UUID(str(invocation.args["deal_id"]))
        restore = dict(invocation.args.get("restore") or {})
        applied = dict(invocation.args.get("applied") or {})
        added = {_contact_key(contact) for contact in invocation.args.get("contacts_added") or []}
        for _ in range(_CONFLICT_RETRIES):
            try:
                current = await deals.get(ctx.user_id, ctx.tenant_id, deal_id)
            except WorkspaceServiceError as exc:
                raise ToolFailed(str(exc), retryable=exc.retryable) from exc
            if current is None:
                raise ToolFailed("the deal no longer exists")
            # Only fields still holding what this update set go back; later edits by others stay.
            restorable = {field: value for field, value in restore.items() if _normalize(current.get(field)) == _normalize(applied.get(field))}
            skipped = sorted(set(restore) - set(restorable))
            contacts = [contact for contact in current.get("contacts") or [] if _contact_key(contact) not in added]
            body = _body(current) | restorable | {"contacts": contacts, "expected_version": current["version"]}
            try:
                await deals.put(ctx.user_id, ctx.tenant_id, deal_id, body)
            except WorkspaceServiceError as exc:
                if exc.status == 409:
                    continue
                raise ToolFailed(str(exc), retryable=exc.retryable) from exc
            result = f"restored {plural(len(restorable), 'field')} of the deal '{current.get('title')}'"
            if skipped:
                result += f"; kept later changes to {', '.join(skipped)}"
            return result
        raise ToolFailed("the deal kept changing while it was being restored", retryable=True)

    return [
        ToolDefinition(
            name="search_deals",
            description="Find the workspace's deals by company or title words, stage, or only the rep's own.",
            kind=ToolKind.READ,
            scope=ToolScope.READ,
            category=ToolCategory.KNOWLEDGE,
            input_model=SearchDealsArgs,
            handler=search_deals,
            timeout_seconds=20,
        ),
        ToolDefinition(
            name="create_deal",
            description=(
                "Record a new sales opportunity (deal) in the workspace: company, title, stage, value, expected close "
                "date, next step, contacts. Check search_deals first so you don't create a duplicate. The rep approves it."
            ),
            kind=ToolKind.WRITE,
            scope=ToolScope.CRM,
            category=ToolCategory.ACTION,
            input_model=CreateDealArgs,
            handler=create_deal,
            timeout_seconds=30,
            acl=writer,
            preview=create_preview,
            undo_handler=delete_created,
        ),
        ToolDefinition(
            name="update_deal",
            description=(
                "Change a deal: stage (e.g. to PROPOSAL after sending a quote, WON or LOST when it closes), value, "
                "expected close date, next step, notes, or add contacts. Only the fields you pass change. The rep approves it."
            ),
            kind=ToolKind.WRITE,
            scope=ToolScope.CRM,
            category=ToolCategory.ACTION,
            input_model=UpdateDealArgs,
            handler=update_deal,
            timeout_seconds=30,
            acl=writer,
            preview=update_preview,
            undo_handler=restore_deal,
        ),
    ]


async def link_quote(
    deals: DealsClient, ctx: AgentContext, deal_id: UUID, quote: dict[str, Any]
) -> str | None:
    """Add a quote to a deal's quotes, retrying on concurrent changes. Returns why it failed, or ``None``."""
    for _ in range(_CONFLICT_RETRIES):
        try:
            current = await deals.get(ctx.user_id, ctx.tenant_id, deal_id)
            if current is None:
                return "the deal no longer exists"
            quotes = [item for item in current.get("quotes") or [] if item.get("number") != quote["number"]] + [quote]
            await deals.put(ctx.user_id, ctx.tenant_id, deal_id, _body(current) | {"quotes": quotes, "expected_version": current["version"]})
            return None
        except WorkspaceServiceError as exc:
            if exc.status == 409:
                await asyncio.sleep(0.05)
                continue
            return str(exc)
    return "the deal kept changing"


async def unlink_quote(deals: DealsClient, ctx: AgentContext, deal_id: UUID, number: str) -> None:
    """Remove a quote from a deal (undo). Safe to repeat."""
    for _ in range(_CONFLICT_RETRIES):
        try:
            current = await deals.get(ctx.user_id, ctx.tenant_id, deal_id)
            if current is None:
                return
            quotes = [item for item in current.get("quotes") or [] if item.get("number") != number]
            if len(quotes) == len(current.get("quotes") or []):
                return
            await deals.put(ctx.user_id, ctx.tenant_id, deal_id, _body(current) | {"quotes": quotes, "expected_version": current["version"]})
            return
        except WorkspaceServiceError as exc:
            if exc.status == 409:
                continue
            raise ToolFailed(str(exc), retryable=exc.retryable) from exc
    raise ToolFailed("the deal kept changing while the quote was being removed", retryable=True)


async def _get_existing(deals: DealsClient, ctx: AgentContext, deal_id: UUID) -> dict[str, Any]:
    try:
        current = await deals.get(ctx.user_id, ctx.tenant_id, deal_id)
    except WorkspaceServiceError as exc:
        raise ToolFailed(str(exc), retryable=exc.retryable) from exc
    if current is None:
        raise ToolInputError(f"there is no deal {deal_id} in this workspace")
    return current


def _body(deal: dict[str, Any]) -> dict[str, Any]:
    """A PUT body carrying the deal's current values (a full replace)."""
    return {
        "title": deal.get("title"),
        "company": deal.get("company"),
        "stage": deal.get("stage"),
        "amount": deal.get("amount"),
        "currency": deal.get("currency"),
        "expected_close_date": deal.get("expected_close_date"),
        "next_step": deal.get("next_step"),
        "notes": deal.get("notes"),
        "contacts": list(deal.get("contacts") or []),
        "quotes": list(deal.get("quotes") or []),
        "source": "AGENT",
    }


def _brief(deal: dict[str, Any]) -> dict[str, Any]:
    return {
        "deal_id": deal.get("deal_id"),
        "title": deal.get("title"),
        "company": deal.get("company"),
        "stage": deal.get("stage"),
        "amount": deal.get("amount"),
        "currency": deal.get("currency"),
        "expected_close_date": deal.get("expected_close_date"),
        "next_step": deal.get("next_step"),
        "owner": deal.get("owner_name"),
        "contacts": [contact.get("name") for contact in deal.get("contacts") or []][:10],
        "quotes": [quote.get("number") for quote in deal.get("quotes") or []][:10],
        "updated_at": deal.get("updated_at"),
    }


def _normalize(value: Any) -> Any:
    """Compare values the way workspace-service stores them (amounts as numbers, empty as None)."""
    if value in ("", None):
        return None
    if isinstance(value, int | float) and not isinstance(value, bool):
        return round(float(value), 2)
    if isinstance(value, str):
        try:
            return round(float(value), 2) if value.replace(".", "", 1).isdigit() else value.strip()
        except ValueError:
            return value.strip()
    return value


def _contact_key(contact: dict[str, Any]) -> str:
    return str(contact.get("email") or contact.get("name") or "").strip().lower()


def _show(value: Any) -> str:
    return "(none)" if value in (None, "") else str(value)


def _money(deal: dict[str, Any]) -> str:
    amount = deal.get("amount")
    return f", {deal.get('currency') or 'USD'} {float(amount):,.2f}" if amount not in (None, "") else ""


def _write_failure(exc: WorkspaceServiceError) -> Exception:
    if exc.maybe_applied:
        return ToolOutcomeUnknown(str(exc))
    if exc.status == 403:
        return ToolAccessDenied(str(exc))
    if exc.status in (400, 422):
        return ToolInputError(str(exc))
    return ToolFailed(str(exc))
