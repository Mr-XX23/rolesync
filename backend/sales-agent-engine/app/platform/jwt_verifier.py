"""Verifies auth-service access tokens (RS256) inside the engine.

The gateway also verifies them (and injects ``X-User-Id``), but this service's port can
be reached directly, so it never trusts that header and checks the ``access_token``
cookie itself. Claims: ``userId`` (auth user UUID, the stable identity), ``email``,
``tokenType`` ("ACCESS"), ``iss``, ``exp``; ``sub`` is a non-unique display name and is
ignored. Revocation (logout) lives only in auth-service, so a logged-out token stays
valid here until it expires.

Keys come from auth-service's JWKS endpoint (so a regenerated key pair is picked up
without copying files), with a configured PEM as fallback.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from uuid import UUID

import httpx
import jwt

from app.core.context import Principal
from app.core.errors import AuthenticationFailed, UpstreamUnavailable

logger = logging.getLogger(__name__)


class SigningKeys:
    def __init__(
        self,
        *,
        jwks_url: str | None = None,
        http: httpx.AsyncClient | None = None,
        pem: str | None = None,
        cache_seconds: float = 300.0,
        min_refresh_seconds: float = 30.0,
    ) -> None:
        if not jwks_url and not pem:
            raise ValueError("configure a JWKS URL or a PEM public key")
        self._jwks_url = jwks_url
        self._http = http
        self._pem = pem
        self._cache_seconds = cache_seconds
        self._min_refresh_seconds = min_refresh_seconds
        self._keys: list[Any] | None = None  # from the last successful JWKS fetch
        self._fetched_at = 0.0
        self._attempted_at: float | None = None

    async def get(self, *, refresh: bool = False) -> list[Any]:
        if self._jwks_url:
            now = time.monotonic()
            stale = self._keys is None or now - self._fetched_at > self._cache_seconds
            since_attempt = float("inf") if self._attempted_at is None else now - self._attempted_at
            # Fetch when the cache is stale or a signature didn't match (key rotation), but never
            # more often than min_refresh_seconds: neither forged tokens nor an unreachable
            # auth-service can turn every request into a JWKS round trip.
            if (stale or refresh) and since_attempt >= self._min_refresh_seconds:
                await self._fetch()
            if self._keys:
                # The PEM is only a fallback: once JWKS answers, a rotated-out key must stop working.
                return list(self._keys)
        if self._pem:
            return [self._pem]
        raise UpstreamUnavailable("token signing keys are unavailable")

    async def _fetch(self) -> None:
        assert self._jwks_url and self._http is not None
        self._attempted_at = time.monotonic()
        try:
            response = await self._http.get(self._jwks_url, timeout=5.0)
            response.raise_for_status()
            keys = [
                jwt.PyJWK(item).key
                for item in response.json().get("keys", [])
                if item.get("kty") == "RSA" and item.get("use", "sig") == "sig"
            ]
        except Exception as exc:
            # Keep any previously fetched keys: a brief auth-service outage must not lock users out.
            logger.warning("could not fetch JWKS from %s: %s", self._jwks_url, exc)
            return
        self._keys = keys
        self._fetched_at = time.monotonic()


class _NoKeyMatched(Exception):
    pass


class AccessTokenVerifier:
    def __init__(self, *, keys: SigningKeys, issuer: str, leeway_seconds: int = 30) -> None:
        self._keys = keys
        self._issuer = issuer
        self._leeway = leeway_seconds

    async def verify(self, token: str) -> Principal:
        claims: dict[str, Any] | None = None
        for refresh in (False, True):
            try:
                claims = self._decode(token, await self._keys.get(refresh=refresh))
                break
            except _NoKeyMatched:
                continue
        if claims is None:
            raise AuthenticationFailed("invalid access token")

        if claims.get("tokenType") != "ACCESS":
            raise AuthenticationFailed("not an access token")
        try:
            user_id = UUID(str(claims["userId"]))
        except ValueError as exc:
            raise AuthenticationFailed("invalid userId claim") from exc
        email = claims.get("email")
        return Principal(user_id=user_id, email=email if isinstance(email, str) else None)

    def _decode(self, token: str, keys: list[Any]) -> dict[str, Any]:
        for key in keys:
            try:
                return jwt.decode(
                    token,
                    key,
                    algorithms=["RS256"],
                    issuer=self._issuer,
                    leeway=self._leeway,
                    options={"require": ["exp", "iss", "userId"]},
                )
            except jwt.InvalidSignatureError:
                continue
            except jwt.ExpiredSignatureError as exc:
                raise AuthenticationFailed("access token expired") from exc
            except jwt.PyJWTError as exc:
                raise AuthenticationFailed("invalid access token") from exc
        raise _NoKeyMatched
