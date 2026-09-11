"""Workspace membership for workspace-scoped routes (knowledge vault, catalog).

The gateway verifies *who* the caller is and injects ``X-User-Id``. *Which workspace* the
caller acts in comes from ``X-Tenant-Id``, which nothing upstream verifies, so these routes
check that the caller is an active member of it. workspace-service is the source of truth;
its answer is cached briefly, and a "not a member" answer is re-checked live once so a
workspace created a moment ago works immediately. If membership can't be verified, the
request is refused (fail closed).
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional
from uuid import UUID

import requests
from fastapi import Header, HTTPException, status

from module_1_document_processing.identity import authed_user_id

ADMIN_ROLES = frozenset({"OWNER", "ADMIN"})

Memberships = Dict[str, Optional[str]]  # workspace id -> caller's role (None if unknown)


@dataclass(frozen=True)
class WorkspaceAccess:
    user_id: str
    workspace_id: str  # canonical lower-case UUID
    role: Optional[str]

    @property
    def can_write(self) -> bool:
        return self.role != "VIEWER"

    @property
    def is_admin(self) -> bool:
        return self.role in ADMIN_ROLES


class MembershipUnavailable(Exception):
    pass


def fetch_memberships(base_url: str, user_id: str, timeout_seconds: float) -> Memberships:
    """The caller's active workspaces and roles, from ``GET /api/v1/workspaces``."""
    try:
        response = requests.get(
            f"{base_url.rstrip('/')}/api/v1/workspaces", headers={"X-User-Id": user_id}, timeout=timeout_seconds
        )
    except requests.RequestException as exc:
        raise MembershipUnavailable(f"workspace-service unreachable: {type(exc).__name__}") from exc
    if response.status_code == 404:  # no workspace profile yet: member of nothing
        return {}
    if response.status_code != 200:
        raise MembershipUnavailable(f"workspace-service answered {response.status_code}")
    memberships: Memberships = {}
    for item in response.json() or []:
        if not isinstance(item, dict) or item.get("isActive") is False:
            continue
        try:
            workspace_id = str(UUID(str(item.get("workspaceId"))))
        except ValueError:
            continue
        memberships[workspace_id] = item.get("role")
    return memberships


class MembershipDirectory:
    def __init__(
        self,
        base_url: str,
        *,
        cache_seconds: float = 60.0,
        timeout_seconds: float = 5.0,
        fetch: Optional[Callable[[str, str, float], Memberships]] = None,
    ) -> None:
        self._base_url = base_url
        self._cache_seconds = cache_seconds
        self._timeout = timeout_seconds
        self._fetch = fetch or fetch_memberships
        self._cache: dict[str, tuple[float, Memberships]] = {}
        self._lock = threading.Lock()

    def access(self, user_id: str, workspace_id: str) -> Optional[WorkspaceAccess]:
        """The caller's access to the workspace, or None if they aren't a member."""
        for fresh in (False, True):
            memberships = self._memberships(user_id, fresh=fresh)
            if workspace_id in memberships:
                return WorkspaceAccess(user_id=user_id, workspace_id=workspace_id, role=memberships[workspace_id])
        return None

    def _memberships(self, user_id: str, *, fresh: bool) -> Memberships:
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(user_id)
        if cached and not fresh and now - cached[0] < self._cache_seconds:
            return cached[1]
        memberships = self._fetch(self._base_url, user_id, self._timeout)
        with self._lock:
            self._cache[user_id] = (now, memberships)
        return memberships


directory = MembershipDirectory(
    os.environ.get("WORKSPACE_SERVICE_URL", "http://workspace-service:8083"),
    cache_seconds=float(os.environ.get("WORKSPACE_MEMBERSHIP_CACHE_SECONDS", "60")),
)


def resolve_workspace_access(user_id: str, tenant_header: Optional[str]) -> WorkspaceAccess:
    """Validate ``X-Tenant-Id`` and the caller's membership of it (HTTP errors on failure)."""
    if not tenant_header or not tenant_header.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing X-Tenant-Id header")
    try:
        workspace_id = str(UUID(tenant_header.strip()))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid X-Tenant-Id '{tenant_header.strip()}': must be a workspace UUID",
        )
    try:
        access = directory.access(user_id, workspace_id)
    except MembershipUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Workspace membership could not be verified ({exc})",
        )
    if access is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not a member of this workspace")
    return access


def require_workspace_member(x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-Id")) -> WorkspaceAccess:
    """Route dependency: the verified caller must be an active member of ``X-Tenant-Id``."""
    return resolve_workspace_access(authed_user_id(), x_tenant_id)


def require_writer(access: WorkspaceAccess) -> None:
    if not access.can_write:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Viewers can't make changes in this workspace")
