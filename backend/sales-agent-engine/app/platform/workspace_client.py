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
        if await self.role_in(user_id, tenant_id) is None:
            raise TenantAccessDenied("you are not a member of this workspace")

    async def role_in(self, user_id: UUID, tenant_id: UUID) -> str | None:
        """The user's role in the workspace (``OWNER``, ``ADMIN``, ``MEMBER``, ``VIEWER``; ``""`` if
        workspace-service didn't say), or ``None`` if they are not a member."""
        roles = await self.roles(user_id)
        if tenant_id not in roles:
            roles = await self.roles(user_id, fresh=True)
        return roles.get(tenant_id)

    async def workspace_ids(self, user_id: UUID, *, fresh: bool = False) -> frozenset[UUID]:
        return frozenset(await self.roles(user_id, fresh=fresh))

    async def roles(self, user_id: UUID, *, fresh: bool = False) -> dict[UUID, str]:
        key = f"{self._prefix}:workspace-roles:{user_id}"
        if not fresh:
            cached = await self._redis.get(key)
            if cached is not None:
                return {UUID(workspace): role for workspace, role in json.loads(cached).items()}
        roles = await self._fetch(user_id)
        await self._redis.set(key, json.dumps({str(workspace): role for workspace, role in roles.items()}), ex=self._ttl)
        return roles

    async def _fetch(self, user_id: UUID) -> dict[UUID, str]:
        try:
            response = await self._http.get(
                f"{self._base_url}/api/v1/workspaces",
                headers={"X-User-Id": str(user_id)},
                timeout=5.0,
            )
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable("workspace-service is unreachable") from exc
        if response.status_code == 404:  # no workspace profile yet
            return {}
        if response.status_code != 200:
            raise UpstreamUnavailable(f"workspace-service returned {response.status_code}")
        roles: dict[UUID, str] = {}
        for workspace in response.json():
            raw_id = workspace.get("workspaceId")
            if raw_id and workspace.get("isActive") is not False:
                roles[UUID(raw_id)] = str(workspace.get("role") or "").upper()
        return roles


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


class WorkspaceServiceError(Exception):
    """workspace-service refused or failed; the message is safe to show to the agent.

    ``status`` is the HTTP status (``None`` if no answer came back); ``maybe_applied`` is set
    when a write may have reached the service without an answer coming back."""

    def __init__(self, message: str, *, status: int | None = None, maybe_applied: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.maybe_applied = maybe_applied
        self.retryable = status is None or status == 429 or status >= 500


@dataclass(frozen=True, slots=True)
class RepProfile:
    first_name: str | None = None
    job_title: str | None = None
    communication_style: str | None = None
    persona_context: str | None = None  # the rep's own words for the agent ("Custom AI Agent Context")


class RepProfileClient:
    """The rep's workspace profile, briefly cached. Best effort: no profile is never an error."""

    def __init__(self, *, base_url: str, http: httpx.AsyncClient, cache_seconds: float = 300.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = http
        self._ttl = cache_seconds
        self._cache: dict[UUID, tuple[float, RepProfile | None]] = {}

    async def get(self, user_id: UUID) -> RepProfile | None:
        import time

        now = time.monotonic()
        cached = self._cache.get(user_id)
        if cached is not None and now - cached[0] < self._ttl:
            return cached[1]
        try:
            response = await self._http.get(
                f"{self._base_url}/api/v1/workspaces/profile", headers={"X-User-Id": str(user_id)}, timeout=5.0
            )
        except httpx.HTTPError:
            return cached[1] if cached is not None else None
        profile = None
        if response.status_code == 200:
            body = response.json() if response.content else {}
            profile = RepProfile(
                first_name=_text_or_none(body.get("firstName")),
                job_title=_text_or_none(body.get("jobTitle")),
                communication_style=_text_or_none(body.get("communicationStyle")),
                persona_context=_text_or_none(body.get("aiPersonaContext")),
            )
        self._cache[user_id] = (now, profile)
        return profile


class DealsClient:
    """Deals shared by a workspace (workspace-service), as the acting user."""

    def __init__(self, *, base_url: str, http: httpx.AsyncClient, timeout_seconds: float = 15.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = http
        self._timeout = timeout_seconds

    async def list(
        self, user_id: UUID, workspace_id: UUID, *, query: str | None = None, stage: str | None = None,
        mine: bool = False, limit: int = 50,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "mine": str(mine).lower()}
        if query:
            params["q"] = query
        if stage:
            params["stage"] = stage
        body = await self._send("GET", f"/api/v1/workspaces/{workspace_id}/deals", user_id, params=params)
        return [deal for deal in body or [] if isinstance(deal, dict)]

    async def get(self, user_id: UUID, workspace_id: UUID, deal_id: UUID) -> dict[str, Any] | None:
        return await self._send("GET", f"/api/v1/workspaces/{workspace_id}/deals/{deal_id}", user_id, missing_ok=True)

    async def put(self, user_id: UUID, workspace_id: UUID, deal_id: UUID, body: dict[str, Any]) -> dict[str, Any]:
        """Create (with this id) or replace a deal. With ``expected_version`` in ``body`` a stale
        write fails with status 409 instead of overwriting someone else's change."""
        return await self._send("PUT", f"/api/v1/workspaces/{workspace_id}/deals/{deal_id}", user_id, json=body)

    async def delete(self, user_id: UUID, workspace_id: UUID, deal_id: UUID, *, expected_version: int | None = None) -> bool:
        """``False`` if the deal was already gone."""
        params = {"expected_version": expected_version} if expected_version is not None else None
        found = await self._send(
            "DELETE", f"/api/v1/workspaces/{workspace_id}/deals/{deal_id}", user_id, params=params, missing_ok=True, empty_ok=True
        )
        return found is not None

    async def _send(
        self, method: str, path: str, user_id: UUID, *, params: Any = None, json: Any = None,
        missing_ok: bool = False, empty_ok: bool = False,
    ) -> Any:
        try:
            response = await self._http.request(
                method, f"{self._base_url}{path}", headers={"X-User-Id": str(user_id)}, params=params, json=json,
                timeout=self._timeout,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            raise WorkspaceServiceError(f"workspace-service unreachable: {type(exc).__name__}") from exc
        except httpx.HTTPError as exc:
            raise WorkspaceServiceError(
                f"workspace-service gave no answer: {type(exc).__name__}", maybe_applied=method != "GET"
            ) from exc
        if response.status_code == 404 and missing_ok:
            return None
        if response.status_code >= 400:
            raise WorkspaceServiceError(
                f"workspace-service {response.status_code}: {_message(response)}", status=response.status_code
            )
        if not response.content:
            return {} if empty_ok else None
        try:
            return response.json()
        except ValueError as exc:
            raise WorkspaceServiceError("workspace-service returned a non-JSON response", status=response.status_code) from exc


def _text_or_none(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _message(response: httpx.Response) -> str:
    try:
        body = response.json()
        detail = body.get("message") if isinstance(body, dict) else None
    except ValueError:
        detail = None
    return str(detail if detail else response.text)[:300]
