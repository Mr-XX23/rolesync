"""Quotes: ``create_quote`` prices catalog items (catalog prices, each item's discount limit,
stock), renders the quote as a document, saves it like any generated document and can hold
the quoted stock. Deals are not recorded yet (decided for this build: quotes only).

Money is computed with ``Decimal`` and rounded half-up to cents per line.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID, uuid5

from pydantic import Field, StringConstraints

from app.core.clock import utcnow
from app.core.context import AgentContext
from app.platform.data_pipeline import DataPipelineClient, DataPipelineError
from app.platform.workspace_client import DealsClient, WorkspaceDirectory, WorkspaceServiceError
from app.tools.adapters.common import as_dict, as_list, pipeline_failure, plural, safe_filename
from app.tools.adapters.deals import link_quote, unlink_quote
from app.tools.adapters.documents import stored_file_result
from app.tools.documents.render import FORMAT_LABELS, MIME_TYPES, Document, Section, Table, render
from app.tools.documents.storage import DESTINATION_LABELS, DocumentStore
from app.tools.registry import ToolDefinition
from app.tools.types import (
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

CENT = Decimal("0.01")
_NAMESPACE = UUID("2f6f7f0e-8a53-4a5e-9a0c-6a4c1d3b7e21")

EmailAddress = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=320)]


class QuoteLineArgs(ToolInput):
    sku: str = Field(min_length=1, max_length=100)
    quantity: int = Field(ge=1, le=1_000_000)
    discount_pct: float = Field(default=0, ge=0, le=100, description="Discount on this line, within the item's limit")


class CreateQuoteArgs(ToolInput):
    customer_company: str = Field(min_length=1, max_length=200)
    customer_contact: str | None = Field(default=None, max_length=200, description="Contact person's name")
    customer_email: EmailAddress | None = None
    items: list[QuoteLineArgs] = Field(min_length=1, max_length=50)
    valid_days: int = Field(default=30, ge=1, le=365)
    notes: str | None = Field(default=None, max_length=4000)
    terms: str | None = Field(default=None, max_length=4000)
    format: Literal["pdf", "docx", "xlsx"] = "pdf"
    reserve_stock: bool = Field(default=False, description="Hold the quoted quantities of physical products in inventory")
    deal_id: UUID | None = Field(default=None, description="Link the quote to this deal (from search_deals)")


@dataclass(frozen=True, slots=True)
class PricedLine:
    sku: str
    name: str
    product_type: str
    quantity: int
    unit_price: Decimal
    discount_pct: Decimal
    subtotal: Decimal
    discount: Decimal
    total: Decimal
    available: int | None  # physical products only


@dataclass(frozen=True, slots=True)
class PricedQuote:
    currency: str
    lines: tuple[PricedLine, ...]
    subtotal: Decimal
    discount: Decimal
    total: Decimal
    issued: date
    valid_until: date
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def summary_lines(self) -> list[dict[str, Any]]:
        return [
            {
                "sku": line.sku,
                "name": line.name,
                "quantity": line.quantity,
                "unit_price": str(line.unit_price),
                "discount_pct": str(line.discount_pct),
                "discount": str(line.discount),
                "total": str(line.total),
                "available": line.available,
            }
            for line in self.lines
        ]


def money(currency: str, amount: Decimal) -> str:
    return f"{currency} {amount:,.2f}"


def _decimal(value: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value if value is not None else default))
    except (InvalidOperation, ValueError):
        return Decimal(default)


def price_lines(
    items: list[QuoteLineArgs],
    catalog: dict[str, tuple[dict[str, Any], dict[str, Any]] | None],
    stock: dict[str, int],
    *,
    reserve_stock: bool,
    issued: date,
    valid_days: int,
) -> PricedQuote:
    """Price a quote from catalog data: ``catalog`` maps SKU → (variant, product) or ``None``,
    ``stock`` maps SKU → units available. Raises ``ToolInputError`` listing every problem."""
    problems: list[str] = []
    warnings: list[str] = []
    lines: list[PricedLine] = []
    currencies: set[str] = set()
    wanted: dict[str, int] = defaultdict(int)
    for item in items:
        wanted[item.sku] += item.quantity

    for item in items:
        found = catalog.get(item.sku)
        if found is None:
            problems.append(f"no SKU '{item.sku}' in the catalog")
            continue
        variant, product = found
        name = str(product.get("name") or item.sku)
        if str(variant.get("status")) != "ACTIVE" or str(product.get("status")) != "ACTIVE":
            problems.append(f"'{name}' ({item.sku}) is not an active catalog item")
            continue
        pct = _decimal(item.discount_pct).quantize(CENT, ROUND_HALF_UP)
        limit = _decimal(product.get("max_discount_pct"))
        if pct > limit:
            problems.append(f"{pct}% off '{name}' ({item.sku}) is above its discount limit of {limit}%")
            continue
        currencies.add(str(variant.get("currency") or "USD").upper())
        unit = _decimal(variant.get("price")).quantize(CENT, ROUND_HALF_UP)
        subtotal = (unit * item.quantity).quantize(CENT, ROUND_HALF_UP)
        discount = (subtotal * pct / 100).quantize(CENT, ROUND_HALF_UP)
        product_type = str(product.get("type") or "PRODUCT")
        available = stock.get(item.sku) if product_type == "PRODUCT" else None
        lines.append(
            PricedLine(item.sku, name, product_type, item.quantity, unit, pct, subtotal, discount, subtotal - discount, available)
        )

    for sku, quantity in wanted.items():
        line = next((line for line in lines if line.sku == sku), None)
        if line is None or line.available is None or line.available >= quantity:
            continue
        message = f"only {line.available} of {quantity} × '{line.name}' ({sku}) in stock"
        (problems if reserve_stock else warnings).append(message)
    if len(currencies) > 1:
        problems.append(f"the items are priced in different currencies ({', '.join(sorted(currencies))}); quote them separately")
    if problems:
        raise ToolInputError("cannot price this quote: " + "; ".join(problems))

    subtotal = sum((line.subtotal for line in lines), Decimal("0.00"))
    discount = sum((line.discount for line in lines), Decimal("0.00"))
    return PricedQuote(
        currency=currencies.pop() if currencies else "USD",
        lines=tuple(lines),
        subtotal=subtotal,
        discount=discount,
        total=subtotal - discount,
        issued=issued,
        valid_until=issued + timedelta(days=valid_days),
        warnings=tuple(warnings),
    )


def quote_document(number: str, quote: PricedQuote, args: CreateQuoteArgs) -> Document:
    contact = ", ".join(part for part in (args.customer_contact, args.customer_email) if part)
    details = [
        ("Quote number", number),
        ("Date", quote.issued.isoformat()),
        ("Valid until", quote.valid_until.isoformat()),
        ("Customer", args.customer_company),
    ]
    if contact:
        details.append(("Contact", contact))
    currency = quote.currency
    items = tuple(
        (
            line.sku,
            line.name,
            line.quantity,
            money(currency, line.unit_price),
            f"{line.discount_pct.normalize():f}%" if line.discount_pct else "—",
            money(currency, line.total),
        )
        for line in quote.lines
    )
    sections = [
        Section(heading="Details", table=Table(columns=("Item", "Value"), rows=tuple(details))),
        Section(heading="Items", table=Table(columns=("SKU", "Item", "Qty", "Unit price", "Discount", "Total"), rows=items)),
        Section(
            heading="Summary",
            table=Table(
                columns=("", "Amount"),
                rows=(
                    ("Subtotal", money(currency, quote.subtotal)),
                    ("Discounts", f"-{money(currency, quote.discount)}" if quote.discount else money(currency, Decimal("0.00"))),
                    ("Total", money(currency, quote.total)),
                ),
            ),
        ),
    ]
    if args.notes:
        sections.append(Section(heading="Notes", paragraphs=(args.notes,)))
    terms = args.terms or f"Prices are in {currency}. This quote is valid until {quote.valid_until.isoformat()}."
    sections.append(Section(heading="Terms", paragraphs=(terms,)))
    return Document(title=f"Quote {number}", subtitle=f"Prepared for {args.customer_company}", sections=tuple(sections))


def quote_tools(
    client: DataPipelineClient,
    store: DocumentStore,
    directory: WorkspaceDirectory,
    *,
    font_path: Path | None = None,
    deals: DealsClient | None = None,
) -> list[ToolDefinition]:
    async def price(ctx: AgentContext, args: CreateQuoteArgs) -> PricedQuote:
        skus = list(dict.fromkeys(item.sku for item in args.items))
        try:
            variants = await asyncio.gather(*(client.variant(ctx.user_id, ctx.tenant_id, sku) for sku in skus))
            product_ids = {str(v["product_id"]) for v in variants if isinstance(v, dict) and v.get("product_id")}
            products = dict(
                zip(
                    product_ids,
                    await asyncio.gather(*(client.product(ctx.user_id, ctx.tenant_id, pid) for pid in product_ids)),
                    strict=True,
                )
            )
            availability = await asyncio.gather(*(client.availability(ctx.user_id, ctx.tenant_id, sku) for sku in skus))
        except DataPipelineError as exc:
            raise pipeline_failure(exc) from exc
        catalog: dict[str, tuple[dict[str, Any], dict[str, Any]] | None] = {}
        stock: dict[str, int] = {}
        for sku, variant, available in zip(skus, variants, availability, strict=True):
            product = products.get(str(variant.get("product_id"))) if isinstance(variant, dict) else None
            catalog[sku] = (variant, product) if isinstance(variant, dict) and isinstance(product, dict) else None
            stock[sku] = int(as_dict(available).get("total_available") or 0)
        return price_lines(
            args.items, catalog, stock, reserve_stock=args.reserve_stock, issued=utcnow().date(), valid_days=args.valid_days
        )

    async def release(ctx: AgentContext, reservation_ids: list[str]) -> list[str]:
        """Release reservations; returns the ones that could not be released."""
        stuck: list[str] = []
        for reservation_id in reservation_ids:
            try:
                await client.release_stock(ctx.user_id, ctx.tenant_id, reservation_id)
            except DataPipelineError as exc:
                if "already been released" not in str(exc) and "No active reservation" not in str(exc):
                    stuck.append(reservation_id)
        return stuck

    async def create_quote(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, CreateQuoteArgs)
        ctx = invocation.ctx
        quote = await price(ctx, args)  # current catalog prices at the moment it runs
        number = f"Q-{quote.issued:%Y%m%d}-{uuid5(_NAMESPACE, f'{ctx.session_id}:{invocation.call_id}').hex[:6].upper()}"

        reservations: list[dict[str, Any]] = []
        if args.reserve_stock:
            wanted: dict[str, int] = defaultdict(int)
            for line in quote.lines:
                if line.product_type == "PRODUCT":
                    wanted[line.sku] += line.quantity
            for sku, quantity in wanted.items():
                try:
                    held = await client.reserve_stock(ctx.user_id, ctx.tenant_id, sku=sku, quantity=quantity)
                except DataPipelineError as exc:
                    stuck = await release(ctx, [r["reservation_id"] for r in reservations])
                    detail = f"; could not release reservations {', '.join(stuck)}" if stuck else ""
                    if exc.maybe_applied:
                        raise ToolOutcomeUnknown(
                            f"no answer while reserving {quantity} × {sku}, so that stock may be held: {exc}{detail}"
                        ) from exc
                    raise ToolFailed(f"could not reserve {quantity} × {sku}: {exc}{detail}") from exc
                reservations.append({"sku": sku, "quantity": quantity, "reservation_id": str(held.get("reservation_id"))})

        document = quote_document(number, quote, args)
        content = await asyncio.to_thread(render, document, args.format, font_path=font_path)
        filename = safe_filename(f"Quote {number} - {args.customer_company}", args.format)
        try:
            stored = await store.save(ctx, filename=filename, content=content, mimetype=MIME_TYPES[args.format])
        except Exception:
            await release(ctx, [r["reservation_id"] for r in reservations])
            raise
        where, links, file_undo = stored_file_result(stored, what="quote")
        held_note = f"; reserved {plural(len(reservations), 'SKU')}" if reservations else ""
        label = file_undo.label + (" and release the reserved stock" if reservations else "")
        linked_deal = None
        if args.deal_id is not None and deals is not None:
            # Linking is part of the record, not the quote: a failure is reported, not fatal.
            entry = {"number": number, "total": float(quote.total), "currency": quote.currency, "link": stored.link,
                     "created_at": utcnow().isoformat()}
            problem = await link_quote(deals, ctx, args.deal_id, entry)
            if problem is None:
                linked_deal = str(args.deal_id)
                held_note += "; linked to the deal"
                label += " and remove it from the deal"
            else:
                held_note += f"; could not link it to the deal ({problem})"
        return ToolOutput(
            data={
                "quote_number": number,
                "customer": args.customer_company,
                "currency": quote.currency,
                "subtotal": str(quote.subtotal),
                "discount": str(quote.discount),
                "total": str(quote.total),
                "valid_until": quote.valid_until.isoformat(),
                "lines": quote.summary_lines(),
                "warnings": list(quote.warnings),
                "reservations": reservations,
                "deal_id": linked_deal,
                **stored.to_dict(),
            },
            summary=f"Quote {number} for {args.customer_company}: {money(quote.currency, quote.total)} "
            f"({plural(len(quote.lines), 'line')}), {where}{held_note}",
            ref_id=number,
            sources=links,
            undo=UndoPlan(
                args={
                    **file_undo.args,
                    "reservation_ids": [r["reservation_id"] for r in reservations],
                    "deal_id": linked_deal,
                    "quote_number": number,
                },
                label=label,
            ),
        )

    async def undo_quote(invocation: UndoInvocation) -> str:
        args = invocation.args
        if args.get("deal_id") and deals is not None:
            await unlink_quote(deals, invocation.ctx, UUID(str(args["deal_id"])), str(args.get("quote_number")))
        stuck = await release(invocation.ctx, [str(item) for item in as_list(args.get("reservation_ids"))])
        if stuck:
            raise ToolFailed(f"could not release reservations {', '.join(stuck)}", retryable=True)
        removed = await store.remove(
            invocation.ctx, destination=str(args["destination"]), file_id=str(args["file_id"]), name=str(args.get("name") or "quote")
        )
        released = f"; released {plural(len(as_list(args.get('reservation_ids'))), 'reservation')}" if args.get("reservation_ids") else ""
        return removed + released

    async def preview(ctx: AgentContext, args: ToolInput) -> dict[str, Any]:
        assert isinstance(args, CreateQuoteArgs)
        quote = await price(ctx, args)
        destination = await store.planned_destination(ctx)
        deal = None
        if args.deal_id is not None and deals is not None:
            try:
                found = await deals.get(ctx.user_id, ctx.tenant_id, args.deal_id)
            except WorkspaceServiceError as exc:
                raise ToolFailed(str(exc), retryable=exc.retryable) from exc
            if found is None:
                raise ToolInputError(f"there is no deal {args.deal_id} in this workspace")
            deal = {"deal_id": str(args.deal_id), "title": found.get("title"), "company": found.get("company")}
        return {
            "kind": "quote",
            "customer": {"company": args.customer_company, "contact": args.customer_contact, "email": args.customer_email},
            "currency": quote.currency,
            "lines": quote.summary_lines(),
            "subtotal": str(quote.subtotal),
            "discount": str(quote.discount),
            "total": str(quote.total),
            "valid_until": quote.valid_until.isoformat(),
            "warnings": list(quote.warnings),
            "reserve_stock": args.reserve_stock,
            "notes": args.notes,
            "terms": args.terms,
            "format": args.format,
            "format_label": FORMAT_LABELS[args.format],
            "destination": DESTINATION_LABELS[destination],
            "deal": deal,
        }

    async def acl(ctx: AgentContext, args: ToolInput) -> None:
        assert isinstance(args, CreateQuoteArgs)
        if args.reserve_stock or args.deal_id is not None:
            role = await directory.role_in(ctx.user_id, ctx.tenant_id)
            if role is None or role == "VIEWER":
                raise ToolAccessDenied(
                    "viewers can't reserve stock or change deals; create the quote without reserving it or linking a deal"
                )

    return [
        ToolDefinition(
            name="create_quote",
            description=(
                "Create a price quote for a customer from catalog SKUs: catalog prices, per-line discounts within each "
                "item's limit, totals, validity date and optional stock reservation. Renders it (PDF by default) and "
                "saves it to the rep's Google Drive, or the workspace knowledge base if Drive isn't available. The rep "
                "sees the priced lines and totals before approving."
            ),
            kind=ToolKind.WRITE,
            scope=ToolScope.DOCUMENT,
            category=ToolCategory.ACTION,
            input_model=CreateQuoteArgs,
            handler=create_quote,
            timeout_seconds=120,
            acl=acl,
            preview=preview,
            undo_handler=undo_quote,
        )
    ]
