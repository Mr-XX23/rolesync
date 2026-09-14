"""An in-memory data-pipeline (catalog, inventory, knowledge vault) behind an httpx
MockTransport, answering like the real routes the engine's write tools use."""

from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from app.platform.data_pipeline import DataPipelineClient

MAIN_WAREHOUSE = "11111111-1111-4111-8111-111111111111"
STORE = "22222222-2222-4222-8222-222222222222"
_BASE = "http://data-pipeline.test"
_VAULT = "/api/v1/knowledge-vault"
VAULT_CATEGORIES = frozenset(
    {"BATTLECARD", "PRICING_PACKAGING", "CASE_STUDY_ROI", "SECURITY_COMPLIANCE", "PRODUCT_SPEC", "CONTRACT_LEGAL", "GENERAL_RESOURCE"}
)


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
    corrections_allowed: bool = True  # data-pipeline lets only workspace OWNER/ADMIN correct a count
    movements: list[dict[str, Any]] = field(default_factory=list)  # the stock ledger, oldest first
    unreachable_pages: set[str] = field(default_factory=set)  # addresses ingest-url can't fetch (502)
    # What the classifier decides when a document is classified again.
    classifier_answer: dict[str, Any] = field(
        default_factory=lambda: {
            "category": "PRICING_PACKAGING", "target_competitor": "Globex", "target_industry": "SaaS",
            "sales_summary": "Globex price points", "sales_tags": ["pricing", "globex"],
        }
    )

    def add_document(self, *, name: str, user_id: Any, **fields: Any) -> dict[str, Any]:
        """A vault document as data-pipeline lists it (indexed, uploaded, unclassified by hand)."""
        document = {
            "doc_id": f"doc_{uuid4().hex[:12]}", "name": name, "type": "PDF", "status": "Indexed", "chunks": 4,
            "category": "GENERAL_RESOURCE", "target_competitor": None, "target_industry": None, "sales_summary": "",
            "sales_tags": [], "classifier_used": "openrouter", "user_id": str(user_id), "source": "USER_UPLOAD",
            "created_at": "2026-09-01T10:00:00+00:00", "last_updated": "2026-09-01T10:05:00+00:00", "metadata": {},
        } | fields
        self.documents[document["doc_id"]] = document
        return document

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

    def _record_movement(self, body: dict[str, Any]) -> httpx.Response:
        return _movement(self, body)

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
        if path == f"{catalog}/inventory/movements" and method == "POST":
            return self._record_movement(body)
        if path == f"{catalog}/inventory/movements" and method == "GET":
            params = request.url.params
            reasons = params.get_list("reason")
            items = [
                entry
                for entry in reversed(self.movements)
                if (not params.get("variant_id") or entry["variant_id"] == params["variant_id"])
                and (not params.get("location_id") or entry["location_id"] == params["location_id"])
                and (not reasons or entry["reason"] in reasons)
            ]
            limit = int(params.get("limit") or 50)
            return _json(200, {"items": items[:limit], "total": len(items), "limit": limit, "offset": 0})
        if path == f"{catalog}/inventory/movements/summary" and method == "GET":
            places = [
                {
                    "location_id": location["id"], "location_name": location["name"], "location_type": "WAREHOUSE",
                    "sellable": location["sellable"],
                    "qty_on_hand": sum(level["on_hand"] for (_, place), level in self.stock.items() if place == location["id"]),
                    "qty_reserved": sum(level["reserved"] for (_, place), level in self.stock.items() if place == location["id"]),
                    "received": sum(e["delta"] for e in self.movements if e["reason"] == "RESTOCK" and e["location_id"] == location["id"]),
                    "sold": -sum(e["delta"] for e in self.movements if e["reason"] == "SALE" and e["location_id"] == location["id"]),
                }
                for location in self.locations
            ]
            return _json(200, {"locations": places, "totals": {"movements": len(self.movements)}})
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
        if path.startswith(_VAULT):
            return self._vault(method, path.removeprefix(_VAULT), body, request)
        return _detail(404, f"no route {method} {path}")

    def _vault(self, method: str, path: str, body: Any, request: httpx.Request) -> httpx.Response:
        """The knowledge vault routes (data-pipeline knowledge_vault_routes.py)."""
        user_id = request.headers["X-User-Id"]
        if path == "/upload" and method == "POST":
            name = re.search(rb'filename="([^"]+)"', request.content)
            document = self.add_document(name=name.group(1).decode() if name else "file", user_id=user_id, status="Parsing", chunks=0)
            document["size_bytes"] = len(request.content)
            return _json(200, {"status": "success", "document": document})
        if path == "/documents" and method == "GET":
            params = request.url.params
            listed = [
                doc
                for doc in reversed(self.documents.values())
                if (params.get("status", "all").lower() in ("all", str(doc.get("status")).lower()))
                and (params.get("category", "all").lower() in ("all", str(doc.get("category")).lower()))
                and (not params.get("search") or params["search"].lower() in str(doc.get("name")).lower())
                and (params.get("mine") != "true" or doc.get("user_id") == user_id)
            ]
            return _json(200, {"status": "success", "count": len(listed), "documents": listed})
        if path == "/ingest-url" and method == "POST":
            url = body["url"].strip()
            host = urlsplit(url).hostname or ""
            try:
                internal = not ipaddress.ip_address(host).is_global
            except ValueError:
                internal = "." not in host
            if internal:
                return _detail(400, "Only pages on the public internet can be added to the knowledge vault.")
            if url in self.unreachable_pages:
                return _detail(502, "We could not fetch that page. Check the address and try again.")
            existing = next((doc for doc in self.documents.values() if doc.get("metadata", {}).get("target_url") == url), None)
            if existing is not None:
                # Like data-pipeline: the page is named after its address unless a title is given, and the
                # classifier decides again unless the request overrides it.
                existing.update(
                    name=(body.get("title") or url).strip(), status="Parsing", chunks=0,
                    category=body.get("category") or "GENERAL_RESOURCE", target_competitor=body.get("target_competitor"),
                )
                return _json(200, {"status": "success", "document": existing})
            document = self.add_document(
                name=(body.get("title") or url).strip(), user_id=user_id, doc_id=f"url_{uuid4().hex[:12]}", type="URL",
                status="Parsing", chunks=0, source="URL_INGEST", metadata={"target_url": url},
                category=body.get("category") or "GENERAL_RESOURCE", target_competitor=body.get("target_competitor"),
            )
            return _json(200, {"status": "success", "document": document})
        match = re.fullmatch(r"/documents/([^/]+)(/[a-z-]+)?", path)
        if match is None:
            return _detail(404, f"no route {method} {path}")
        document = self.documents.get(match.group(1))
        if document is None:
            return _detail(404, "Document not found.")
        action = match.group(2)
        if action is None and method == "DELETE":
            del self.documents[document["doc_id"]]
            return _json(200, {"status": "success", "doc_id": document["doc_id"]})
        if action == "/sales-classification" and method == "PATCH":
            if body.get("category") and body["category"].upper() in VAULT_CATEGORIES:
                document["category"] = body["category"].upper()
            for key in ("target_competitor", "target_industry"):
                if body.get(key) is not None:
                    document[key] = body[key].strip() or None
            if body.get("sales_summary") is not None:
                document["sales_summary"] = body["sales_summary"].strip()
            if body.get("sales_tags") is not None:
                document["sales_tags"] = [tag.strip() for tag in body["sales_tags"] if tag.strip()][:8]
            document["classifier_used"] = "manual_user_override"
            return _json(200, {"status": "success", "document": document})
        if action == "/reclassify" and method == "POST":
            document.update(self.classifier_answer, classifier_used="openrouter")
            return _json(200, {"status": "success", "document": document})
        if action == "/reindex" and method == "POST":
            document.update(status="Parsing", chunks=0)
            return _json(200, {"status": "success", "document": document})
        return _detail(404, f"no route {method} {path}")


def _location_named(pipeline: FakeDataPipeline, location_id: str) -> dict[str, Any]:
    return next(location for location in pipeline.locations if location["id"] == location_id)


def _write(pipeline: FakeDataPipeline, variant: dict[str, Any], location_id: str, delta: int, reason: str, body: dict[str, Any]) -> dict[str, Any]:
    level = pipeline.stock.setdefault((variant["id"], location_id), {"on_hand": 0, "reserved": 0})
    level["on_hand"] += delta
    entry = {
        "id": str(uuid4()), "variant_id": variant["id"], "sku": variant["sku"], "location_id": location_id,
        "location_name": _location_named(pipeline, location_id)["name"], "reason": reason, "delta": delta,
        "type": {"RESTOCK": "RECEIVED", "SALE": "SOLD", "TRANSFER_OUT": "SHIPPED_OUT", "TRANSFER_IN": "SHIPPED_IN",
                 "DAMAGE": "DAMAGED", "LOST": "LOST", "RETURN": "RETURNED"}.get(reason, "CORRECTION"),
        "on_hand_after": level["on_hand"], "reference": body.get("reference"), "counterparty": body.get("counterparty"),
        "note": body.get("note"),
    }
    pipeline.movements.append(entry)
    return entry


def _movement(pipeline: FakeDataPipeline, body: dict[str, Any]) -> httpx.Response:
    """The rules of POST /catalog/inventory/movements (data-pipeline catalog/service.py record_movement)."""
    variant = next((v for p in pipeline.products.values() for v in p["variants"] if v["id"] == body["variant_id"]), None)
    if variant is None:
        return _detail(404, "Variant not found")
    kind, qty, location_id = body["type"], body["qty"], body["location_id"]
    location = _location_named(pipeline, location_id)
    level = pipeline.stock.setdefault((variant["id"], location_id), {"on_hand": 0, "reserved": 0})
    before = {location_id: level["on_hand"]}
    if kind == "COUNT_CORRECTION":
        if not pipeline.corrections_allowed:
            return _detail(403, "Only workspace owners and admins can correct a stock count")
        if not (body.get("note") or "").strip():
            return _detail(400, "Say why the count is being corrected")
        if body.get("expected_on_hand") is not None and body["expected_on_hand"] != level["on_hand"]:
            return _detail(409, f"The stock changed: {level['on_hand']} on hand, not {body['expected_on_hand']}")
        if qty < level["reserved"]:
            return _detail(400, "The count can't go below reserved units")
        if qty != level["on_hand"]:
            _write(pipeline, variant, location_id, qty - level["on_hand"], "ADJUST", body)
    elif qty < 1:
        return _detail(400, "Enter a quantity of at least 1")
    elif kind == "SOLD" and not location["sellable"]:
        return _detail(400, f"{location['name']} is not a sellable location")
    elif kind in ("SOLD", "SHIPPED", "DAMAGED", "LOST") and qty > level["on_hand"] - level["reserved"]:
        return _detail(400, f"Only {level['on_hand'] - level['reserved']} available")
    elif kind == "RECEIVED":
        _write(pipeline, variant, location_id, qty, "RESTOCK", body)
    elif kind in ("SOLD", "DAMAGED", "LOST"):
        _write(pipeline, variant, location_id, -qty, {"SOLD": "SALE", "DAMAGED": "DAMAGE", "LOST": "LOST"}[kind], body)
    elif kind == "SHIPPED":
        target = body["to_location_id"]
        before[target] = pipeline.stock.get((variant["id"], target), {"on_hand": 0})["on_hand"]
        _write(pipeline, variant, location_id, -qty, "TRANSFER_OUT", body)
        _write(pipeline, variant, target, qty, "TRANSFER_IN", body)
    elif kind == "RETURNED":
        _write(pipeline, variant, location_id, qty, "RETURN", body)
        if body.get("resellable") is False:
            _write(pipeline, variant, location_id, -qty, "DAMAGE", body)
    levels = [
        {
            "location_id": place, "location_name": _location_named(pipeline, place)["name"], "qty_on_hand_before": was,
            "qty_on_hand": pipeline.stock[(variant["id"], place)]["on_hand"],
            "qty_reserved": pipeline.stock[(variant["id"], place)]["reserved"], "qty_available": 0,
        }
        for place, was in before.items()
    ]
    return _json(200, {"type": kind, "ref_id": str(uuid4()), "changed": True, "levels": levels, "movements": []})


def stock_of(pipeline: FakeDataPipeline, sku: str, location: str = MAIN_WAREHOUSE) -> dict[str, int]:
    variant = pipeline.variant_by_sku(sku)
    assert variant is not None
    return pipeline.stock.get((variant["id"], location), {"on_hand": 0, "reserved": 0})


def price_of(pipeline: FakeDataPipeline, sku: str) -> Decimal:
    variant = pipeline.variant_by_sku(sku)
    assert variant is not None
    return Decimal(str(variant["price"]))
