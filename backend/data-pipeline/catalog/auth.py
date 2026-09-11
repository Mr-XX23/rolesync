import logging
from typing import Optional
from uuid import UUID
from fastapi import HTTPException, Request, status

logger = logging.getLogger("catalog.auth")


class CatalogContext:
    def __init__(self, tenant_id: UUID, user_id: str):
        self.tenant_id = tenant_id
        self.user_id = user_id

    def __repr__(self):
        return f"CatalogContext(tenant_id={self.tenant_id}, user_id={self.user_id})"


def get_catalog_context(request: Request) -> CatalogContext:
    """
    Derive the caller's identity and tenant from the gateway-verified headers.

    The API gateway validates the RS256 access-token cookie and injects a trusted
    ``X-User-Id`` (stripping any client-supplied copy). We therefore take the user
    id from that header only — never from an unverified JWT or a client-chosen
    value, and there is no ``system`` fallback. ``X-Tenant-Id`` (the workspace the
    caller is acting in) is required and must be a UUID.

    NOTE: this establishes *who* the caller is and *which* tenant they claim.
    Verifying that the caller is a MEMBER of that tenant is a separate
    workspace-service check (tracked as a follow-up); catalog queries are already
    scoped by this tenant id in the service layer.
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

    return CatalogContext(tenant_id=tenant_uuid, user_id=user_id_str.strip())
