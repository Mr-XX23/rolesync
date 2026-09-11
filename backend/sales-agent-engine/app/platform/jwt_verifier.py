"""Verifies auth-service access tokens (RS256).

auth-service signs with its RSA private key and puts the token in the HttpOnly
``access_token`` cookie. Claims: ``userId`` (auth user UUID, the stable identity),
``email``, ``tokenType`` ("ACCESS"), ``iss``, ``exp``. ``sub`` is a display username and
is not unique, so it is ignored. The gateway does not verify tokens, so this service must.
Revocation (logout) is tracked only inside auth-service, so a logged-out token stays
valid here until it expires.
"""

from __future__ import annotations

from uuid import UUID

import jwt

from app.core.context import Principal
from app.core.errors import AuthenticationFailed


class AccessTokenVerifier:
    def __init__(self, *, public_key_pem: str, issuer: str, leeway_seconds: int = 30) -> None:
        self._key = public_key_pem
        self._issuer = issuer
        self._leeway = leeway_seconds

    def verify(self, token: str) -> Principal:
        try:
            claims = jwt.decode(
                token,
                self._key,
                algorithms=["RS256"],
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": ["exp", "iss", "userId"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthenticationFailed("access token expired") from exc
        except jwt.PyJWTError as exc:
            raise AuthenticationFailed("invalid access token") from exc

        if claims.get("tokenType") != "ACCESS":
            raise AuthenticationFailed("not an access token")
        try:
            user_id = UUID(str(claims["userId"]))
        except ValueError as exc:
            raise AuthenticationFailed("invalid userId claim") from exc
        email = claims.get("email")
        return Principal(user_id=user_id, email=email if isinstance(email, str) else None)
