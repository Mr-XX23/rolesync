"""
Request identity for data-pipeline routes.

The gateway verifies the RS256 access-token cookie and injects a trusted
``X-User-Id`` header (stripping any client-supplied copy). data-pipeline never
sees a raw JWT, so it takes the caller's identity from that header only — it
must NOT trust a ``user_id`` field in the request body/query, which the caller
controls and previously allowed acting as any user.

``bind_identity`` is an *async* dependency so the ContextVar it sets is visible
both to async route handlers (same task context) and to sync handlers (Starlette
copies the request context into the threadpool worker). Attach it once at the
router level; read the value inside handlers via ``authed_user_id()``.
"""

import contextvars

from fastapi import Header, HTTPException, status

_auth_user_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "data_pipeline_auth_user_id", default=None
)


async def bind_identity(x_user_id: str | None = Header(default=None, alias="X-User-Id")) -> None:
    """Router dependency: require the gateway-verified identity and bind it for this request."""
    if not x_user_id or not x_user_id.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    _auth_user_id.set(x_user_id.strip())


def authed_user_id() -> str:
    """The gateway-verified caller id for the current request, or 401 if unbound."""
    uid = _auth_user_id.get()
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return uid


def require_tenant(x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id")) -> str:
    """Tenant (workspace) the caller is acting in. Required; membership is enforced per-resource."""
    if not x_tenant_id or not x_tenant_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-Tenant-Id header",
        )
    return x_tenant_id.strip()
