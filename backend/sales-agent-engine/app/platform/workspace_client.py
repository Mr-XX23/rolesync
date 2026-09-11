"""workspace-service adapters: membership (who may act in a workspace) and records (where
user-facing work — goals, tasks, notes — is kept for later retrieval).

The tenant is a workspace UUID chosen by the client (``X-Tenant-Id``). Before acting in
it, the engine confirms the verified user belongs to it by asking workspace-service
for that user's active workspaces. Positive answers are cached briefly; a tenant not in
the cached set is always re-checked live before being denied, so a just-created
workspace works immediately.

Service-to-service calls carry the acting user as ``X-User-Id``: workspace-service
authorizes every call against that user's membership, the same as for gateway traffic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

import httpx
from redis.asyncio import Redis

from app.core.errors import TenantAccessDenied, UpstreamUnavailable


class WorkspaceDirectory:
    def __init__(
        self,
        *,
        base_url: str,
        http: httpx.AsyncClient,
        redis: Redis,
        key_prefix: str,
        cache_seconds: int,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = http
        self._redis = redis
        self._prefix = key_prefix
        self._ttl = cache_seconds

    async def require_member(self, user_id: UUID, tenant_id: UUID) -> None:
        if tenant_id in await self.workspace_ids(user_id):
            return
        if tenant_id not in await self.workspace_ids(user_id, fresh=True):
            raise TenantAccessDenied("you are not a member of this workspace")

    async def workspace_ids(self, user_id: UUID, *, fresh: bool = False) -> frozenset[UUID]:
        key = f"{self._prefix}:workspaces:{user_id}"
        if not fresh:
            cached = await self._redis.get(key)
            if cached is not None:
                return frozenset(UUID(value) for value in json.loads(cached))
        ids = await self._fetch(user_id)
        await self._redis.set(key, json.dumps(sorted(str(value) for value in ids)), ex=self._ttl)
        return ids

    async def _fetch(self, user_id: UUID) -> frozenset[UUID]:
        try:
            response = await self._http.get(
                f"{self._base_url}/api/v1/workspaces",
                headers={"X-User-Id": str(user_id)},
                timeout=5.0,
            )
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable("workspace-service is unreachable") from exc
        if response.status_code == 404:  # no workspace profile yet
            return frozenset()
        if response.status_code != 200:
            raise UpstreamUnavailable(f"workspace-service returned {response.status_code}")
        ids: set[UUID] = set()
        for workspace in response.json():
            raw_id = workspace.get("workspaceId")
            if raw_id and workspace.get("isActive") is not False:
                ids.add(UUID(raw_id))
        return frozenset(ids)


class DeliveryResult(StrEnum):
    DELIVERED = "DELIVERED"
    RETRY = "RETRY"  # transient: network, 404 (parent not there yet), 429, 5xx
    REJECTED = "REJECTED"  # permanent: validation, membership revoked, id owned by someone else


@dataclass(frozen=True, slots=True)
class Delivery:
    result: DeliveryResult
    detail: str | None = None
    not_found: bool = False  # 404: the parent record isn't there (yet)


class WorkspaceRecordsClient:
    """Idempotent upserts of agent work into workspace-service (client-chosen ids)."""

    def __init__(self, *, base_url: str, http: httpx.AsyncClient) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = http

    async def put_context(
        self, *, user_id: UUID, workspace_id: UUID, context_id: UUID, payload: dict[str, Any]
    ) -> Delivery:
        return await self._put(f"/api/v1/workspaces/{workspace_id}/contexts/{context_id}", user_id, payload)

    async def put_task(self, *, user_id: UUID, context_id: UUID, task_id: UUID, payload: dict[str, Any]) -> Delivery:
        return await self._put(f"/api/v1/workspaces/contexts/{context_id}/tasks/{task_id}", user_id, payload)

    async def put_note(self, *, user_id: UUID, context_id: UUID, note_id: UUID, payload: dict[str, Any]) -> Delivery:
        return await self._put(f"/api/v1/workspaces/contexts/{context_id}/notes/{note_id}", user_id, payload)

    async def _put(self, path: str, user_id: UUID, payload: dict[str, Any]) -> Delivery:
        try:
            response = await self._http.put(
                f"{self._base_url}{path}", json=payload, headers={"X-User-Id": str(user_id)}, timeout=10.0
            )
        except httpx.HTTPError as exc:
            return Delivery(DeliveryResult.RETRY, f"workspace-service unreachable: {type(exc).__name__}")
        status = response.status_code
        if 200 <= status < 300:
            return Delivery(DeliveryResult.DELIVERED)
        detail = f"workspace-service {status}: {response.text[:300]}"
        if status == 404:
            return Delivery(DeliveryResult.RETRY, detail, not_found=True)
        if status in (408, 425, 429) or status >= 500:
            return Delivery(DeliveryResult.RETRY, detail)
        return Delivery(DeliveryResult.REJECTED, detail)
