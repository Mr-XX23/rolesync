"""Request-scoped dependencies. Identity is established here and nowhere else.

- ``Principal``: the ``access_token`` cookie (or ``Authorization: Bearer``) verified
  against auth-service's public key.
- ``TenantContext``: ``X-Tenant-Id`` (a workspace UUID) confirmed against
  workspace-service membership for that principal.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request

from app.container import Container
from app.core.context import Principal, TenantContext
from app.core.errors import AuthenticationFailed, BadRequest


def get_container(request: Request) -> Container:
    return request.app.state.container


ContainerDep = Annotated[Container, Depends(get_container)]


async def get_principal(request: Request, container: ContainerDep) -> Principal:
    token = request.cookies.get(container.settings.auth_cookie_name)
    if not token:
        scheme, _, credentials = request.headers.get("Authorization", "").partition(" ")
        if scheme.lower() == "bearer" and credentials.strip():
            token = credentials.strip()
    if not token:
        raise AuthenticationFailed("missing access token")
    return container.token_verifier.verify(token)


PrincipalDep = Annotated[Principal, Depends(get_principal)]


async def get_tenant(request: Request, principal: PrincipalDep, container: ContainerDep) -> TenantContext:
    raw = request.headers.get("X-Tenant-Id")
    if not raw:
        raise BadRequest("X-Tenant-Id header is required")
    try:
        tenant_id = UUID(raw)
    except ValueError as exc:
        raise BadRequest("X-Tenant-Id must be a workspace UUID") from exc
    await container.workspaces.require_member(principal.user_id, tenant_id)
    return TenantContext(tenant_id=tenant_id, principal=principal)


TenantDep = Annotated[TenantContext, Depends(get_tenant)]
