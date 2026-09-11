import logging
from typing import Optional
from uuid import UUID
from fastapi import Depends, HTTPException, Request, status

from module_1_document_processing.workspace_access import WorkspaceAccess, require_writer, resolve_workspace_access

logger = logging.getLogger("catalog.auth")


class CatalogContext:
    def __init__(self, tenant_id: UUID, user_id: str, role: Optional[str] = None):
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.role = role  # the caller's role in the workspace, as reported by workspace-service

    def __repr__(self):
        return f"CatalogContext(tenant_id={self.tenant_id}, user_id={self.user_id}, role={self.role})"


def get_catalog_context(request: Request) -> CatalogContext:
    """
    Derive the caller's identity and tenant from the gateway-verified headers.

    The API gateway validates the RS256 access-token cookie and injects a trusted
    ``X-User-Id`` (stripping any client-supplied copy). We therefore take the user
    id from that header only — never from an unverified JWT or a client-chosen
    value, and there is no ``system`` fallback. ``X-Tenant-Id`` (the workspace the
    caller is acting in) is required and must be a UUID.

    The caller must also be an active member of that workspace (checked with
    workspace-service, see ``workspace_access``); catalog queries are then scoped
    by this tenant id in the service layer.
    """
    user_id_str: Optional[str] = (
        request.headers.get("X-User-Id")
        or request.headers.get("X-Auth-User-Id")
    )
    if not user_id_str or not user_id_str.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: missing gateway-verified X-User-Id",
        )

    tenant_id_str: Optional[str] = (
        request.headers.get("X-Tenant-Id")
        or request.headers.get("X-Workspace-Id")
    )
    if not tenant_id_str or not tenant_id_str.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-Tenant-Id header",
        )

    try:
        tenant_uuid = UUID(str(tenant_id_str).strip())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid tenant_id format '{tenant_id_str}': must be a valid UUID",
        )

    access = resolve_workspace_access(user_id_str.strip(), str(tenant_uuid))
    return CatalogContext(tenant_id=tenant_uuid, user_id=access.user_id, role=access.role)


def get_catalog_writer_context(ctx: CatalogContext = Depends(get_catalog_context)) -> CatalogContext:
    """
    ``get_catalog_context`` for routes that change catalog data.

    The caller's role in the workspace must also allow writing: every member except
    a VIEWER, the same rule (and 403) as the knowledge vault.
    """
    require_writer(WorkspaceAccess(user_id=ctx.user_id, workspace_id=str(ctx.tenant_id), role=ctx.role))
    return ctx
