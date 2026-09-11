"""An in-memory data-pipeline (catalog, inventory, knowledge vault uploads) behind an httpx
MockTransport, answering like the real routes the engine's write tools use."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx

from app.platform.data_pipeline import DataPipelineClient

MAIN_WAREHOUSE = "11111111-1111-4111-8111-111111111111"
STORE = "22222222-2222-4222-8222-222222222222"
_BASE = "http://data-pipeline.test"


def _json(status: int, body: Any) -> httpx.Response:
    return httpx.Response(status, json=body)


def _detail(status: int, message: str) -> httpx.Response:
    return httpx.Response(status, json={"detail": message})


@dataclass
class FakeDataPipeline:
    categories: set[str] = field(default_factory=lambda: {"software", "apparel"})
    locations: list[dict[str, Any]] = field(
        default_factory=lambda: [{"id": MAIN_WAREHOUSE, "name": "Main warehouse", "sellable": True, "priority": 1}]
    )
    products: dict[str, dict[str, Any]] = field(default_factory=dict)
    stock: dict[tuple[str, str], dict[str, int]] = field(default_factory=dict)  # (variant id, location id)
    reservations: dict[str, dict[str, Any]] = field(default_factory=dict)
    documents: dict[str, dict[str, Any]] = field(default_factory=dict)
    requests: list[tuple[str, str, Any]] = field(default_factory=list)
    failures: dict[tuple[str, str], int] = field(default_factory=dict)  # (METHOD, path) → status, once
    forbid_writes: bool = False

    # ------------------------------------------------------------------ setup
    def add_product(
        self,
        *,
        name: str,
        sku: str,
        price: str,
        type: str = "PRODUCT",
        status: str = "ACTIVE",
        max_discount_pct: str = "20.00",
        currency: str = "USD",
        on_hand: int = 0,
        location: str = MAIN_WAREHOUSE,
    ) -> dict[str, Any]:
        product_id = str(uuid4())
        variant_id = str(uuid4())
        option_value = {"id": str(uuid4()), "value": "Standard"}
        product = {
            "id": product_id,
            "name": name,
            "type": type,
            "category": "software",
            "status": status,
            "description": f"{name} description",
            "min_discount_pct": "0.00",
            "max_discount_pct": max_discount_pct,
            "keywords": [],
            "variants": [
                {
                    "id": variant_id,
                    "product_id": product_id,
                    "sku": sku,
                    "barcode": f"BAR-{sku}",
                    "price": price,
                    "currency": currency,
                    "weight": "1.50",
                    "status": status if status == "RETIRED" else "ACTIVE",
                    "option_values": [option_value],
                }
            ],
        }
        self.products[product_id] = product
        if on_hand:
            self.stock[(variant_id, location)] = {"on_hand": on_hand, "reserved": 0}
        return product

    def client(self) -> DataPipelineClient:
        return DataPipelineClient(base_url=_BASE, http=httpx.AsyncClient(transport=self.transport()))

    def variant_by_sku(self, sku: str) -> dict[str, Any] | None:
        for product in self.products.values():
            for variant in product["variants"]:
                if variant["sku"] == sku:
                    return variant
        return None

    def paths(self, method: str | None = None) -> list[str]:
        return [path for verb, path, _ in self.requests if method is None or verb == method]

    # ------------------------------------------------------------------ transport
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        method, path = request.method, request.url.path
        body: Any = None
        if request.headers.get("content-type", "").startswith("application/json"):
            body = json.loads(request.content or b"null")
        self.requests.append((method, path, body))
        if not request.headers.get("X-User-Id") or not request.headers.get("X-Tenant-Id"):
            return _detail(401, "missing identity")
        if (method, path) in self.failures:
            return _detail(self.failures.pop((method, path)), "injected failure")
        if self.forbid_writes and method != "GET":
            return _detail(403, "Viewers can't change this workspace's data.")
        try:
            return self._route(method, path, body, request)
        except KeyError as exc:
            return _detail(404, f"{exc} not found")

    def _route(self, method: str, path: str, body: Any, request: httpx.Request) -> httpx.Response:
        catalog = "/api/v1/catalog"
        if path == f"{catalog}/categories" and method == "GET":
            return _json(200, [{"key": key, "label": key.title()} for key in sorted(self.categories)])
        if path == f"{catalog}/locations" and method == "GET":
            return _json(200, self.locations)
        if path == f"{catalog}/products" and method == "POST":
            if body["category"] not in self.categories:
                return _detail(400, f"Category '{body['category']}' does not exist in tenant vocabulary")
            product = {**body, "id": str(uuid4()), "variants": []}
            self.products[product["id"]] = product
            return _json(201, product)
        if match := re.fullmatch(rf"{catalog}/products/([^/]+)", path):
            product = self.products[match.group(1)]
            if method == "GET":
                return _json(200, product)
            if method == "PUT":
                product.update(body)
                return _json(200, product)
            if method == "DELETE":
                product["status"] = "RETIRED"
                for variant in product["variants"]:
                    variant["status"] = "RETIRED"
                return _json(200, product)
        if (match := re.fullmatch(rf"{catalog}/products/([^/]+)/variants", path)) and method == "POST":
            product = self.products[match.group(1)]
            for incoming in body["variants"]:
                existing = self.variant_by_sku(incoming["sku"])
                if existing is not None and existing["product_id"] != product["id"]:
                    return _detail(400, f"SKU '{incoming['sku']}' already exists for a different product in this tenant")
                values = [{"id": value_id, "value": "?"} for value_id in incoming.get("option_value_ids") or []]
                fields = {key: incoming.get(key) for key in ("barcode", "price", "currency", "weight", "status")}
                if existing is None:
                    product["variants"].append(
                        {"id": str(uuid4()), "product_id": product["id"], "sku": incoming["sku"], **fields, "option_values": values}
                    )
                else:
                    existing.update(fields, option_values=values)
            return _json(200, product["variants"])
        if match := re.fullmatch(rf"{catalog}/variants/([^/]+)", path):
            variant = self.variant_by_sku(match.group(1))
            return _json(200, variant) if variant else _detail(404, "Variant not found")
        if match := re.fullmatch(rf"{catalog}/variants/([^/]+)/availability", path):
            variant = self.variant_by_sku(match.group(1))
            if variant is None:
                return _detail(404, "Variant not found")
            levels = [
                {
                    "location_id": location["id"],
                    "location_name": location["name"],
                    "sellable": location["sellable"],
                    "qty_on_hand": level["on_hand"],
                    "qty_reserved": level["reserved"],
                    "qty_available": max(0, level["on_hand"] - level["reserved"]),
                }
                for location in self.locations
                if (level := self.stock.get((variant["id"], location["id"])))
            ]
            return _json(
                200,
                {"variant_id": variant["id"], "sku": variant["sku"], "total_available": sum(l["qty_available"] for l in levels), "by_location": levels},
            )
        if path == f"{catalog}/inventory/set-stock" and method == "POST":
            level = self.stock.setdefault((body["variant_id"], body["location_id"]), {"on_hand": 0, "reserved": 0})
            if body["qty"] < level["reserved"]:
                return _detail(400, "Cannot set qty_on_hand below reserved")
            level["on_hand"] = body["qty"]
            return _json(200, {"qty_on_hand": level["on_hand"], "qty_reserved": level["reserved"]})
        if path == f"{catalog}/inventory/reserve" and method == "POST":
            variant = self.variant_by_sku(body["sku"])
            if variant is None:
                return _detail(400, "Variant not found")
            wanted, allocations = body["qty"], []
            for location in self.locations:
                if body.get("location_id") and location["id"] != body["location_id"]:
                    continue
                level = self.stock.get((variant["id"], location["id"]))
                if not level:
                    continue
                take = min(wanted, level["on_hand"] - level["reserved"])
                if take > 0:
                    allocations.append((level, location, take))
                    wanted -= take
            if wanted > 0:
                return _detail(400, f"Insufficient stock: requested {body['qty']}")
            reservation_id = str(uuid4())
            for level, _, take in allocations:
                level["reserved"] += take
            self.reservations[reservation_id] = {"allocations": allocations, "released": False, "sku": body["sku"]}
            return _json(
                200,
                {
                    "reservation_id": reservation_id,
                    "sku": body["sku"],
                    "requested_qty": body["qty"],
                    "allocated_qty": body["qty"],
                    "allocations": [{"location_id": loc["id"], "location_name": loc["name"], "qty": take} for _, loc, take in allocations],
                },
            )
        if (match := re.fullmatch(rf"{catalog}/inventory/release/([^/]+)", path)) and method == "POST":
            reservation = self.reservations.get(match.group(1))
            if reservation is None:
                return _detail(400, f"No active reservation found with ID '{match.group(1)}'")
            if reservation["released"]:
                return _detail(400, f"Reservation '{match.group(1)}' has already been released")
            for level, _, take in reservation["allocations"]:
                level["reserved"] -= take
            reservation["released"] = True
            released = sum(take for _, _, take in reservation["allocations"])
            return _json(200, {"reservation_id": match.group(1), "released_qty": released, "movements_count": 1})
        if path == "/api/v1/knowledge-vault/upload" and method == "POST":
            name = re.search(rb'filename="([^"]+)"', request.content)
            doc_id = f"doc_{uuid4().hex[:12]}"
            document = {"doc_id": doc_id, "name": name.group(1).decode() if name else "file", "size_bytes": len(request.content)}
            self.documents[doc_id] = document
            return _json(200, {"status": "success", "document": document})
        if (match := re.fullmatch(r"/api/v1/knowledge-vault/documents/([^/]+)", path)) and method == "DELETE":
            if self.documents.pop(match.group(1), None) is None:
                return _detail(404, "Document not found.")
            return _json(200, {"status": "success"})
        return _detail(404, f"no route {method} {path}")


def stock_of(pipeline: FakeDataPipeline, sku: str, location: str = MAIN_WAREHOUSE) -> dict[str, int]:
    variant = pipeline.variant_by_sku(sku)
    assert variant is not None
    return pipeline.stock.get((variant["id"], location), {"on_hand": 0, "reserved": 0})


def price_of(pipeline: FakeDataPipeline, sku: str) -> Decimal:
    variant = pipeline.variant_by_sku(sku)
    assert variant is not None
    return Decimal(str(variant["price"]))
