from __future__ import annotations

import asyncio

import pytest
from pydantic import SecretStr

from app.config import Settings
from tests.support import RsaKeys, generate_rsa_keys

TEST_DB_NAME = "rolesync-micro-sales-agent-test"


def pytest_asyncio_loop_factories(config, item):
    # psycopg's async mode (LangGraph checkpointer) cannot run on Windows' Proactor loop.
    return {"selector": asyncio.SelectorEventLoop}


@pytest.fixture(scope="session")
def rsa_keys() -> RsaKeys:
    return generate_rsa_keys()


@pytest.fixture(scope="session")
def settings(rsa_keys: RsaKeys) -> Settings:
    settings = Settings(
        db_name=TEST_DB_NAME,
        redis_db=15,
        redis_key_prefix="sae-test",
        jwt_public_key_pem=SecretStr(rsa_keys.public_pem),
        jwt_issuer="rolesync-test-issuer",
        workspace_service_url="http://workspace.test",
        eureka_enabled=False,
        sse_ping_seconds=1,
        approval_ttl_seconds=3600,
        tool_timeout_seconds=2.0,
    )
    assert settings.sqlalchemy_url.database == TEST_DB_NAME, "tests must never touch the dev database"
    return settings
