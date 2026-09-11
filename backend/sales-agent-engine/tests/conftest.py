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


def pytest_addoption(parser):
    parser.addoption("--live", action="store_true", default=False, help="run tests that call real vendor APIs")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--live"):
        return
    skip_live = pytest.mark.skip(reason="calls real vendor APIs; run with --live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


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
        jwt_jwks_url=None,
        jwt_issuer="rolesync-test-issuer",
        workspace_service_url="http://workspace.test",
        eureka_enabled=False,
        sse_ping_seconds=1,
        approval_ttl_seconds=3600,
        tool_timeout_seconds=2.0,
        # Never reach real vendors from the default test run (backend/.env holds live keys).
        gemini_api_key=None,
        openrouter_api_key=None,
        composio_api_key=None,
        langsmith_tracing=False,
        workspace_sync_interval_seconds=0.05,
        run_lease_seconds=5,
    )
    assert settings.sqlalchemy_url.database == TEST_DB_NAME, "tests must never touch the dev database"
    return settings
