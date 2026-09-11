from __future__ import annotations

import time
from uuid import uuid4

import jwt
import pytest

from app.core.errors import AuthenticationFailed
from app.platform.jwt_verifier import AccessTokenVerifier
from tests.support import RsaKeys, generate_rsa_keys, make_token

ISSUER = "rolesync-test-issuer"


@pytest.fixture(scope="module")
def verifier(rsa_keys: RsaKeys) -> AccessTokenVerifier:
    return AccessTokenVerifier(public_key_pem=rsa_keys.public_pem, issuer=ISSUER, leeway_seconds=0)


def test_valid_access_token_yields_user_id_claim_not_sub(verifier, rsa_keys):
    user_id = uuid4()
    principal = verifier.verify(make_token(rsa_keys, user_id, issuer=ISSUER))
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
def test_rejected_tokens(verifier, rsa_keys, overrides, reason):
    params = {"issuer": ISSUER, **overrides}
    with pytest.raises(AuthenticationFailed, match=reason):
        verifier.verify(make_token(rsa_keys, uuid4(), **params))


def test_token_signed_by_another_key_is_rejected(verifier):
    forged = make_token(generate_rsa_keys(), uuid4(), issuer=ISSUER)
    with pytest.raises(AuthenticationFailed):
        verifier.verify(forged)


def test_hs256_token_using_public_key_as_secret_is_rejected(verifier, rsa_keys):
    # Algorithm-confusion attack: only RS256 is accepted.
    now = int(time.time())
    claims = {"iss": ISSUER, "userId": str(uuid4()), "tokenType": "ACCESS", "exp": now + 60}
    try:
        forged = jwt.encode(claims, rsa_keys.public_pem, algorithm="HS256")
    except jwt.InvalidKeyError:
        pytest.skip("PyJWT refuses to sign HS256 with a PEM key (already safe)")
    with pytest.raises(AuthenticationFailed):
        verifier.verify(forged)


def test_garbage_is_rejected(verifier):
    with pytest.raises(AuthenticationFailed):
        verifier.verify("not.a.jwt")
