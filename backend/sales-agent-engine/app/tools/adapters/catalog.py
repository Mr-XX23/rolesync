"""Product and service catalog reads over data-pipeline's catalog API (scoped by workspace).

Prices and discount bounds arrive as decimal strings (e.g. ``"199.99"``) and are passed on
unchanged so no rounding creeps in.
"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import Field

from app.platform.data_pipeline import DataPipelineClient, DataPipelineError
from app.tools.adapters.common import as_dict, as_list, clip, plural
from app.tools.registry import ToolDefinition
from app.tools.types import ToolCategory, ToolFailed, ToolInput, ToolInvocation, ToolKind, ToolOutput, ToolScope


class SearchCatalogArgs(ToolInput):
    query: str = Field(min_length=2, max_length=300, description="A need, product name, use case or SKU")
    max_results: int = Field(default=5, ge=1, le=10)
    include_inactive: bool = Field(default=False, description="Also return draft and retired items")


class CheckInventoryArgs(ToolInput):
    skus: list[str] = Field(min_length=1, max_length=20)
    quantity: int | None = Field(default=None, ge=1, le=1_000_000, description="Units needed of each SKU")


def catalog_tools(client: DataPipelineClient) -> list[ToolDefinition]:
    async def search_catalog(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, SearchCatalogArgs)
        ctx = invocation.ctx
        try:
            # Ask for extra matches: drafts and retired items are dropped below unless requested.
            found = await client.search_products(ctx.user_id, ctx.tenant_id, args.query, limit=args.max_results * 2)
        except DataPipelineError as exc:
            raise ToolFailed(str(exc)) from exc
        items = [
            _item(product, match, include_inactive=args.include_inactive)
            for product, match in found
            if args.include_inactive or product.get("status") == "ACTIVE"
        ][: args.max_results]
        return ToolOutput(data={"items": items}, summary=f"{plural(len(items), 'catalog item')} matching '{args.query}'")

    async def check_inventory(invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, CheckInventoryArgs)
        ctx = invocation.ctx
        skus = list(dict.fromkeys(sku.strip() for sku in args.skus if sku.strip()))
        try:
            stock = await asyncio.gather(*(client.availability(ctx.user_id, ctx.tenant_id, sku) for sku in skus))
        except DataPipelineError as exc:
            raise ToolFailed(str(exc)) from exc
        items = [_stock(sku, entry, args.quantity) for sku, entry in zip(skus, stock, strict=True)]
        return ToolOutput(data={"items": items}, summary=_stock_summary(items, args.quantity))

    return [
        ToolDefinition(
            name="search_catalog",
            description=(
                "Search the workspace's product and service catalog. Returns matching items with description, "
                "value proposition, use cases, SKUs with prices, and the allowed discount range."
            ),
            kind=ToolKind.READ,
            scope=ToolScope.READ,
            category=ToolCategory.KNOWLEDGE,
            input_model=SearchCatalogArgs,
            handler=search_catalog,
            timeout_seconds=45,  # data-pipeline may expand the query with an LLM first
        ),
        ToolDefinition(
            name="check_inventory",
            description="Check available stock for catalog SKUs, optionally against a needed quantity.",
            kind=ToolKind.READ,
            scope=ToolScope.READ,
            category=ToolCategory.KNOWLEDGE,
            input_model=CheckInventoryArgs,
            handler=check_inventory,
            timeout_seconds=30,
        ),
    ]


def _item(product: dict[str, Any], match: dict[str, Any], *, include_inactive: bool) -> dict[str, Any]:
    option_names = {str(option.get("id")): option.get("name") for option in map(as_dict, as_list(product.get("options")))}
    variants = [
        {
            "sku": variant.get("sku"),
            "price": variant.get("price"),
            "currency": variant.get("currency"),
            "status": variant.get("status"),
            "options": {
                str(option_names.get(str(value.get("option_id")), "option")): value.get("value")
                for value in map(as_dict, as_list(variant.get("option_values")))
            },
        }
        for variant in map(as_dict, as_list(product.get("variants")))
        if include_inactive or variant.get("status") != "RETIRED"
    ]
    return {
        "product_id": product.get("id"),
        "name": product.get("name"),
        "type": product.get("type"),
        "category": product.get("category"),
        "status": product.get("status"),
        "description": clip(product.get("description"), 500),
        "value_proposition": clip(product.get("value_proposition"), 300),
        "use_cases": as_list(product.get("use_cases"))[:5],
        "target_industries": as_list(product.get("target_industries"))[:5],
        "beats_competitors": as_list(product.get("competitors_beats"))[:5],
        "discount_pct": {"min": product.get("min_discount_pct"), "max": product.get("max_discount_pct")},
        "variants": variants[:10],
        "match": {"score": match.get("score"), "why": match.get("rationale")},
    }


def _stock(sku: str, entry: Any, quantity: int | None) -> dict[str, Any]:
    if not isinstance(entry, dict):
        return {"sku": sku, "found": False}
    available = _int(entry.get("total_available"))
    locations = [
        {"location": location.get("location_name"), "available": _int(location.get("qty_available"))}
        for location in map(as_dict, as_list(entry.get("by_location")))
        if location.get("sellable") and _int(location.get("qty_available")) > 0
    ]
    return {
        "sku": sku,
        "found": True,
        "available": available,
        "can_fulfill": available >= quantity if quantity else None,
        "locations": locations[:10],
    }


def _stock_summary(items: list[dict[str, Any]], quantity: int | None) -> str:
    found = [item for item in items if item["found"]]
    parts = []
    if found and quantity:
        parts.append(f"{sum(1 for item in found if item['can_fulfill'])} of {len(found)} can supply {quantity}")
    elif found:
        parts.append(f"{len(found)} found")
    if len(found) < len(items):
        parts.append(f"{len(items) - len(found)} not found")
    return f"Stock for {plural(len(items), 'SKU')}: " + ", ".join(parts)


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0
