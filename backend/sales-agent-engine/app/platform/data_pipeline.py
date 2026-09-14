"""data-pipeline over HTTP: the knowledge vault and the product catalog (one service).

The engine calls it inside the platform network, where data-pipeline trusts ``X-User-Id``
(outside, the gateway sets it from a verified token), so every call carries the verified
user of the run and nothing from a model. Both the vault and the catalog are shared per
workspace: every call names the session's workspace in ``X-Tenant-Id``, and data-pipeline
checks the user is a member of it before answering.
"""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

_PAGE_FETCH_TIMEOUT = 45.0  # data-pipeline waits up to 12 s for the page, then scans and stores it
_CLASSIFY_TIMEOUT = 110.0  # a model call, with fallbacks between models


class DataPipelineError(Exception):
    """data-pipeline failed or refused; the message is safe to show to the agent.

    ``status`` is the HTTP status (``None`` if no answer came back). ``retryable`` marks
    failures worth trying again: no answer, rate limiting, server errors. ``maybe_applied``
    is set when the request may have reached data-pipeline but no answer came back, so a
    write may or may not have happened."""

    def __init__(self, message: str, *, status: int | None = None, maybe_applied: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = status is None or status == 429 or status >= 500
        self.maybe_applied = maybe_applied


class DataPipelineClient:
    def __init__(self, *, base_url: str, http: httpx.AsyncClient, timeout_seconds: float = 20.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = http
        self._timeout = timeout_seconds

    # ------------------------------------------------------------------ knowledge vault
    async def list_documents(
        self,
        user_id: UUID,
        tenant_id: UUID,
        *,
        category: str | None = None,
        status: str | None = "Indexed",
        search: str | None = None,
        mine: bool = False,
    ) -> list[dict[str, Any]]:
        """The workspace's documents, newest first (data-pipeline has no pagination). By default only
        indexed ones; ``status=None`` lists every state (Parsing, Indexed, Error, Rejected)."""
        params: dict[str, Any] = {}
        if status:
            params["status"] = status
        if category:
            params["category"] = category
        if search:
            params["search"] = search
        if mine:
            params["mine"] = "true"
        body = await self._get("/api/v1/knowledge-vault/documents", user_id, tenant_id=tenant_id, params=params)
        return [doc for doc in body.get("documents") or [] if isinstance(doc, dict)]

    async def ingest_url(
        self,
        user_id: UUID,
        tenant_id: UUID,
        *,
        url: str,
        title: str | None = None,
        category: str | None = None,
        competitor: str | None = None,
    ) -> dict[str, Any]:
        """Fetch a public web page into the vault (indexed in the background). The same address again
        refreshes its existing document."""
        payload = {"url": url, "title": title, "category": category, "target_competitor": competitor}
        body = await self._send(
            "POST",
            "/api/v1/knowledge-vault/ingest-url",
            user_id,
            tenant_id=tenant_id,
            json={key: value for key, value in payload.items() if value},
            timeout=_PAGE_FETCH_TIMEOUT,
        )
        document = body.get("document") if isinstance(body, dict) else None
        if not isinstance(document, dict) or not document.get("doc_id"):
            raise DataPipelineError("data-pipeline accepted the page but returned no document id", status=200)
        return document

    async def update_document_classification(
        self, user_id: UUID, tenant_id: UUID, doc_id: str, changes: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Set a document's category, competitor, industry, summary or tags (only the keys given; an empty
        competitor or industry clears it). ``None`` if the workspace has no such document."""
        body = await self._send(
            "PATCH",
            f"/api/v1/knowledge-vault/documents/{quote(doc_id, safe='')}/sales-classification",
            user_id,
            tenant_id=tenant_id,
            json=changes,
            missing_ok=True,
        )
        return _document_of(body)

    async def reclassify_document(self, user_id: UUID, tenant_id: UUID, doc_id: str) -> dict[str, Any] | None:
        """Classify a document again with the model, replacing its classification (a model call: slow)."""
        body = await self._send(
            "POST",
            f"/api/v1/knowledge-vault/documents/{quote(doc_id, safe='')}/reclassify",
            user_id,
            tenant_id=tenant_id,
            missing_ok=True,
            timeout=_CLASSIFY_TIMEOUT,
        )
        return _document_of(body)

    async def reindex_document(self, user_id: UUID, tenant_id: UUID, doc_id: str) -> dict[str, Any] | None:
        """Rebuild a document's search index from its stored content (in the background)."""
        body = await self._send(
            "POST", f"/api/v1/knowledge-vault/documents/{quote(doc_id, safe='')}/reindex", user_id, tenant_id=tenant_id, missing_ok=True
        )
        return _document_of(body)

    async def document_text(self, user_id: UUID, tenant_id: UUID, doc_id: str) -> dict[str, Any] | None:
        """A document's full text, or ``None`` if the workspace has no such document."""
        return await self._get(
            f"/api/v1/knowledge-vault/documents/{quote(doc_id, safe='')}/content", user_id, tenant_id=tenant_id, missing_ok=True
        )

    async def upload_document(
        self, user_id: UUID, tenant_id: UUID, *, filename: str, content: bytes, mimetype: str, category: str | None = None
    ) -> dict[str, Any]:
        """Add a file to the workspace's knowledge vault (parsed and indexed in the background)."""
        body = await self._send(
            "POST",
            "/api/v1/knowledge-vault/upload",
            user_id,
            tenant_id=tenant_id,
            files={"file": (filename, content, mimetype)},
            data={"category": category} if category else None,
        )
        document = body.get("document") if isinstance(body, dict) else None
        if not isinstance(document, dict) or not document.get("doc_id"):
            raise DataPipelineError("data-pipeline accepted the upload but returned no document id", status=200)
        return document

    async def search_knowledge(self, user_id: UUID, tenant_id: UUID, query: str, *, limit: int) -> list[dict[str, Any]] | None:
        """Semantic search over the workspace's indexed passages, best first. Each hit has the matched
        ``text``, the wider ``context`` around it, ``doc_id`` and ``score``. ``None`` on data-pipeline
        builds without the endpoint; a 503 means search is briefly unavailable."""
        body = await self._send(
            "POST", "/api/v1/knowledge-vault/search", user_id, tenant_id=tenant_id, json={"query": query, "limit": limit}, missing_ok=True
        )
        if body is None:
            return None
        return [hit for hit in body.get("results") or [] if isinstance(hit, dict)]

    async def delete_document(self, user_id: UUID, tenant_id: UUID, doc_id: str) -> bool:
        """Remove a vault document; ``False`` if it was already gone."""
        found = await self._send(
            "DELETE", f"/api/v1/knowledge-vault/documents/{quote(doc_id, safe='')}", user_id, tenant_id=tenant_id, missing_ok=True
        )
        return found is not None

    # ------------------------------------------------------------------ catalog reads
    async def search_products(
        self, user_id: UUID, tenant_id: UUID, query: str, limit: int
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """``(product, match)`` pairs, best first. Uses the catalog's relevance-ranked search, or its
        keyword filter on data-pipeline builds that predate it (matches then come newest first)."""
        ranked = await self._send(
            "POST",
            "/api/v1/catalog/ai/semantic-search",
            user_id,
            tenant_id=tenant_id,
            # No LLM query expansion: the agent already writes precise queries, and it costs seconds.
            json={"query": query, "limit": limit, "expand": False},
            missing_ok=True,
        )
        if ranked is None:
            listed = await self._get(
                "/api/v1/catalog/products", user_id, tenant_id=tenant_id, params={"keywords": query, "limit": limit}
            )
            return [(product, {"score": None, "rationale": "keyword match"}) for product in listed if isinstance(product, dict)]
        matches = [match for match in ranked.get("results") or [] if isinstance(match, dict)]
        products = await asyncio.gather(
            *(self._get(f"/api/v1/catalog/products/{match.get('product_id')}", user_id, tenant_id=tenant_id, missing_ok=True) for match in matches)
        )
        return [(product, match) for product, match in zip(products, matches, strict=True) if isinstance(product, dict)]

    async def availability(self, user_id: UUID, tenant_id: UUID, sku: str) -> dict[str, Any] | None:
        """Stock of one SKU across locations; ``None`` if there is no such SKU."""
        return await self._get(f"/api/v1/catalog/variants/{quote(sku, safe='')}/availability", user_id, tenant_id=tenant_id, missing_ok=True)

    async def product(self, user_id: UUID, tenant_id: UUID, product_id: str) -> dict[str, Any] | None:
        """A product with its options and variants; ``None`` if the workspace has no such product."""
        return await self._get(f"/api/v1/catalog/products/{quote(product_id, safe='')}", user_id, tenant_id=tenant_id, missing_ok=True)

    async def variant(self, user_id: UUID, tenant_id: UUID, sku: str) -> dict[str, Any] | None:
        return await self._get(f"/api/v1/catalog/variants/{quote(sku, safe='')}", user_id, tenant_id=tenant_id, missing_ok=True)

    async def categories(self, user_id: UUID, tenant_id: UUID) -> list[dict[str, Any]]:
        body = await self._get("/api/v1/catalog/categories", user_id, tenant_id=tenant_id)
        return [item for item in body or [] if isinstance(item, dict)]

    async def locations(self, user_id: UUID, tenant_id: UUID) -> list[dict[str, Any]]:
        body = await self._get("/api/v1/catalog/locations", user_id, tenant_id=tenant_id)
        return [item for item in body or [] if isinstance(item, dict)]

    # ------------------------------------------------------------------ catalog writes
    async def create_product(self, user_id: UUID, tenant_id: UUID, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._send("POST", "/api/v1/catalog/products", user_id, tenant_id=tenant_id, json=payload)

    async def update_product(self, user_id: UUID, tenant_id: UUID, product_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Partial update: only the fields in ``payload`` change."""
        return await self._send(
            "PUT", f"/api/v1/catalog/products/{quote(product_id, safe='')}", user_id, tenant_id=tenant_id, json=payload
        )

    async def retire_product(self, user_id: UUID, tenant_id: UUID, product_id: str) -> dict[str, Any] | None:
        """Soft delete: the product and all its variants become RETIRED (never a hard delete)."""
        return await self._send(
            "DELETE", f"/api/v1/catalog/products/{quote(product_id, safe='')}", user_id, tenant_id=tenant_id, missing_ok=True
        )

    async def upsert_variants(
        self, user_id: UUID, tenant_id: UUID, product_id: str, variants: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Create or fully overwrite variants by SKU (every field, including option values)."""
        body = await self._send(
            "POST",
            f"/api/v1/catalog/products/{quote(product_id, safe='')}/variants",
            user_id,
            tenant_id=tenant_id,
            json={"variants": variants},
        )
        return [item for item in body or [] if isinstance(item, dict)]

    async def record_stock_movement(self, user_id: UUID, tenant_id: UUID, payload: dict[str, Any]) -> dict[str, Any]:
        """One thing that happened to stock (received, sold, shipped, damaged, lost, returned, or a count
        correction). The ledger is append-only: a mistake is fixed by recording another movement."""
        return await self._send("POST", "/api/v1/catalog/inventory/movements", user_id, tenant_id=tenant_id, json=payload)

    async def stock_movements(self, user_id: UUID, tenant_id: UUID, params: dict[str, Any]) -> dict[str, Any]:
        """Stock history, newest first: ``{items, total, limit, offset}``."""
        return await self._get("/api/v1/catalog/inventory/movements", user_id, tenant_id=tenant_id, params=params)

    async def stock_summary(self, user_id: UUID, tenant_id: UUID, params: dict[str, Any]) -> dict[str, Any]:
        """Per-location totals of each kind of movement, with current stock: ``{locations, totals}``."""
        return await self._get("/api/v1/catalog/inventory/movements/summary", user_id, tenant_id=tenant_id, params=params)

    async def reserve_stock(
        self, user_id: UUID, tenant_id: UUID, *, sku: str, quantity: int, location_id: str | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"sku": sku, "qty": quantity}
        if location_id:
            payload["location_id"] = location_id
        return await self._send("POST", "/api/v1/catalog/inventory/reserve", user_id, tenant_id=tenant_id, json=payload)

    async def release_stock(self, user_id: UUID, tenant_id: UUID, reservation_id: str) -> dict[str, Any]:
        return await self._send(
            "POST", f"/api/v1/catalog/inventory/release/{quote(reservation_id, safe='')}", user_id, tenant_id=tenant_id
        )

    # ------------------------------------------------------------------ transport
    async def _get(
        self, path: str, user_id: UUID, *, tenant_id: UUID | None = None, params: Any = None, missing_ok: bool = False
    ) -> Any:
        return await self._send("GET", path, user_id, tenant_id=tenant_id, params=params, missing_ok=missing_ok)

    async def _send(
        self,
        method: str,
        path: str,
        user_id: UUID,
        *,
        tenant_id: UUID | None = None,
        params: Any = None,
        json: Any = None,
        files: Any = None,
        data: Any = None,
        missing_ok: bool = False,
        timeout: float | None = None,
    ) -> Any:
        headers = {"X-User-Id": str(user_id)}
        if tenant_id is not None:
            headers["X-Tenant-Id"] = str(tenant_id)
        try:
            response = await self._http.request(
                method,
                f"{self._base_url}{path}",
                headers=headers,
                params=params,
                json=json,
                files=files,
                data=data,
                timeout=timeout or self._timeout,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            raise DataPipelineError(f"data-pipeline unreachable: {type(exc).__name__}") from exc
        except httpx.HTTPError as exc:  # sent, but no complete answer
            raise DataPipelineError(f"data-pipeline gave no answer: {type(exc).__name__}", maybe_applied=True) from exc
        if response.status_code == 404 and missing_ok:
            return None
        if response.status_code >= 400:
            raise DataPipelineError(f"data-pipeline {response.status_code}: {_detail(response)}", status=response.status_code)
        try:
            return response.json()
        except ValueError as exc:
            raise DataPipelineError("data-pipeline returned a non-JSON response", status=response.status_code) from exc


def _document_of(body: Any) -> dict[str, Any] | None:
    if body is None:
        return None
    document = body.get("document") if isinstance(body, dict) else None
    if not isinstance(document, dict):
        raise DataPipelineError("data-pipeline answered without the document", status=200)
    return document


def _detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    return str(detail if detail is not None else response.text)[:300]
