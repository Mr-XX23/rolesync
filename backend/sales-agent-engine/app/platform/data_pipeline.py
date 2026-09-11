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


class DataPipelineError(Exception):
    """data-pipeline failed or refused; the message is safe to show to the agent."""


class DataPipelineClient:
    def __init__(self, *, base_url: str, http: httpx.AsyncClient, timeout_seconds: float = 20.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = http
        self._timeout = timeout_seconds

    # ------------------------------------------------------------------ knowledge vault
    async def list_documents(self, user_id: UUID, tenant_id: UUID, *, category: str | None = None) -> list[dict[str, Any]]:
        """The workspace's indexed documents, newest first (data-pipeline has no pagination)."""
        params = {"status": "Indexed"}
        if category:
            params["category"] = category
        body = await self._get("/api/v1/knowledge-vault/documents", user_id, tenant_id=tenant_id, params=params)
        return [doc for doc in body.get("documents") or [] if isinstance(doc, dict)]

    async def document_text(self, user_id: UUID, tenant_id: UUID, doc_id: str) -> dict[str, Any] | None:
        """A document's full text, or ``None`` if the workspace has no such document."""
        return await self._get(
            f"/api/v1/knowledge-vault/documents/{quote(doc_id, safe='')}/content", user_id, tenant_id=tenant_id, missing_ok=True
        )

    # ------------------------------------------------------------------ catalog
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
        missing_ok: bool = False,
    ) -> Any:
        headers = {"X-User-Id": str(user_id)}
        if tenant_id is not None:
            headers["X-Tenant-Id"] = str(tenant_id)
        try:
            response = await self._http.request(
                method, f"{self._base_url}{path}", headers=headers, params=params, json=json, timeout=self._timeout
            )
        except httpx.HTTPError as exc:
            raise DataPipelineError(f"data-pipeline unreachable: {type(exc).__name__}") from exc
        if response.status_code == 404 and missing_ok:
            return None
        if response.status_code >= 400:
            raise DataPipelineError(f"data-pipeline {response.status_code}: {_detail(response)}")
        try:
            return response.json()
        except ValueError as exc:
            raise DataPipelineError("data-pipeline returned a non-JSON response") from exc


def _detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    return str(detail if detail is not None else response.text)[:200]
