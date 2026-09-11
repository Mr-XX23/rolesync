from __future__ import annotations

import json
import time
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from jwt.algorithms import RSAAlgorithm

from app.core.errors import AuthenticationFailed
from app.platform.jwt_verifier import AccessTokenVerifier, SigningKeys
from tests.support import RsaKeys, generate_rsa_keys, make_token

ISSUER = "rolesync-test-issuer"


@pytest.fixture(scope="module")
def verifier(rsa_keys: RsaKeys) -> AccessTokenVerifier:
    return AccessTokenVerifier(keys=SigningKeys(pem=rsa_keys.public_pem), issuer=ISSUER, leeway_seconds=0)


async def test_valid_access_token_yields_user_id_claim_not_sub(verifier, rsa_keys):
    user_id = uuid4()
    principal = await verifier.verify(make_token(rsa_keys, user_id, issuer=ISSUER))
    assert principal.user_id == user_id
    assert principal.email == "rep@example.com"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"expires_in": -60}, "expired"),
        ({"issuer": "someone-else"}, "invalid"),
        ({"token_type": "REFRESH"}, "not an access token"),
        ({"userId": None}, "invalid"),
        ({"userId": "not-a-uuid"}, "userId"),
    ],
)
async def test_rejected_tokens(verifier, rsa_keys, overrides, reason):
    params = {"issuer": ISSUER, **overrides}
    with pytest.raises(AuthenticationFailed, match=reason):
        await verifier.verify(make_token(rsa_keys, uuid4(), **params))


async def test_token_signed_by_another_key_is_rejected(verifier):
    with pytest.raises(AuthenticationFailed):
        await verifier.verify(make_token(generate_rsa_keys(), uuid4(), issuer=ISSUER))


async def test_hs256_token_using_public_key_as_secret_is_rejected(verifier, rsa_keys):
    # Algorithm-confusion attack: only RS256 is accepted.
    now = int(time.time())
    claims = {"iss": ISSUER, "userId": str(uuid4()), "tokenType": "ACCESS", "exp": now + 60}
    try:
        forged = jwt.encode(claims, rsa_keys.public_pem, algorithm="HS256")
    except jwt.InvalidKeyError:
        pytest.skip("PyJWT refuses to sign HS256 with a PEM key (already safe)")
    with pytest.raises(AuthenticationFailed):
        await verifier.verify(forged)


async def test_garbage_is_rejected(verifier):
    with pytest.raises(AuthenticationFailed):
        await verifier.verify("not.a.jwt")


def _jwks(keys: RsaKeys) -> dict:
    jwk = json.loads(RSAAlgorithm.to_jwk(load_pem_public_key(keys.public_pem.encode())))
    jwk["use"] = "sig"
    return {"keys": [jwk]}


async def test_jwks_keys_pick_up_a_rotated_key_pair():
    """auth-service regenerates its key pair when keys are missing; JWKS lets the engine follow."""
    old, new = generate_rsa_keys(), generate_rsa_keys()
    current = {"keys": old}
    fetches = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal fetches
        fetches += 1
        return httpx.Response(200, json=_jwks(current["keys"]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        keys = SigningKeys(jwks_url="http://auth.test/jwks", http=http, min_refresh_seconds=0)
        verifier = AccessTokenVerifier(keys=keys, issuer=ISSUER)
        user = uuid4()
        assert (await verifier.verify(make_token(old, user, issuer=ISSUER))).user_id == user

        current["keys"] = new  # rotation: the cached key no longer matches new tokens
        assert (await verifier.verify(make_token(new, user, issuer=ISSUER))).user_id == user
        assert fetches == 2
        with pytest.raises(AuthenticationFailed):
            await verifier.verify(make_token(generate_rsa_keys(), user, issuer=ISSUER))


async def test_pem_is_only_a_fallback_while_jwks_is_unavailable():
    configured, served = generate_rsa_keys(), generate_rsa_keys()
    jwks_up = False

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_jwks(served)) if jwks_up else httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        keys = SigningKeys(
            jwks_url="http://auth.test/jwks", http=http, pem=configured.public_pem, cache_seconds=0, min_refresh_seconds=0
        )
        verifier = AccessTokenVerifier(keys=keys, issuer=ISSUER)
        user = uuid4()
        # auth-service's JWKS is down: tokens signed with the configured key still work.
        assert (await verifier.verify(make_token(configured, user, issuer=ISSUER))).user_id == user

        jwks_up = True  # once JWKS answers, it alone decides which keys are valid
        assert (await verifier.verify(make_token(served, user, issuer=ISSUER))).user_id == user
        with pytest.raises(AuthenticationFailed):
            await verifier.verify(make_token(configured, user, issuer=ISSUER))


async def test_bad_tokens_cannot_turn_every_request_into_a_jwks_fetch():
    fetches = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal fetches
        fetches += 1
        return httpx.Response(503)

    signer = generate_rsa_keys()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        keys = SigningKeys(jwks_url="http://auth.test/jwks", http=http, pem=signer.public_pem, min_refresh_seconds=30)
        verifier = AccessTokenVerifier(keys=keys, issuer=ISSUER)
        for _ in range(5):
            with pytest.raises(AuthenticationFailed):
                await verifier.verify(make_token(generate_rsa_keys(), uuid4(), issuer=ISSUER))  # unknown signer
        assert (await verifier.verify(make_token(signer, uuid4(), issuer=ISSUER))).email == "rep@example.com"

    assert fetches == 1
