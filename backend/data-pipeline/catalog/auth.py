import base64
import json
import logging
from typing import Optional
from uuid import UUID
from fastapi import HTTPException, Request, status

try:
    import jwt
except ImportError:
    jwt = None

logger = logging.getLogger("catalog.auth")


class CatalogContext:
    def __init__(self, tenant_id: UUID, user_id: str):
        self.tenant_id = tenant_id
        self.user_id = user_id

    def __repr__(self):
        return f"CatalogContext(tenant_id={self.tenant_id}, user_id={self.user_id})"


def _decode_token_claims(token: str) -> dict:
    """Decode unverified JWT claims using PyJWT or base64 fallback."""
    if jwt is not None:
        try:
            return jwt.decode(token, options={"verify_signature": False})
        except Exception:
            pass

    # Fallback to manual payload decoding
    parts = token.split(".")
    if len(parts) >= 2:
        payload_b64 = parts[1]
        # Fix padding
        padding = 4 - (len(payload_b64) % 4)
        if padding != 4:
            payload_b64 += "=" * padding
        try:
            payload_bytes = base64.urlsafe_b64decode(payload_b64)
            return json.loads(payload_bytes)
        except Exception as e:
            logger.debug(f"Manual base64 JWT decode error: {e}")
    return {}


def get_catalog_context(request: Request) -> CatalogContext:
    """Extract tenant_id and user_id from Authorization Bearer JWT or fallback headers."""
    tenant_id_str: Optional[str] = None
    user_id_str: Optional[str] = None

    # 1. Try Bearer JWT
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        claims = _decode_token_claims(token)
        tenant_id_str = (
            claims.get("tenant_id")
            or claims.get("tenantId")
            or claims.get("workspace_id")
            or claims.get("workspaceId")
        )
        user_id_str = (
            claims.get("user_id")
            or claims.get("userId")
            or claims.get("sub")
        )

    # 2. Fallback to custom headers or request.state
    if not tenant_id_str:
        tenant_id_str = (
            request.headers.get("X-Tenant-Id")
            or request.headers.get("X-Workspace-Id")
            or getattr(request.state, "tenant_id", None)
        )

    if not user_id_str:
        user_id_str = (
            request.headers.get("X-User-Id")
            or request.headers.get("X-Auth-User-Id")
            or getattr(request.state, "user_id", None)
            or "system"
        )

    if not tenant_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: tenant_id missing from JWT token and X-Tenant-Id header",
        )

    try:
        tenant_uuid = UUID(str(tenant_id_str))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid tenant_id format '{tenant_id_str}': must be a valid UUID",
        )

    return CatalogContext(tenant_id=tenant_uuid, user_id=str(user_id_str))
