"""Offline tests for data-pipeline request identity binding.

Each case runs bind + read inside the SAME coroutine so the ContextVar set by
bind_identity is visible to authed_user_id (mirrors FastAPI: an async dependency
sets it in the request task's context, which sync handlers inherit via the
threadpool context copy).
"""

import asyncio

import pytest
from fastapi import HTTPException

from module_1_document_processing.identity import (
    authed_user_id,
    bind_identity,
    require_tenant,
)


def test_authed_user_id_unbound_raises_401():
    async def run():
        return authed_user_id()

    with pytest.raises(HTTPException) as ei:
        asyncio.run(run())
    assert ei.value.status_code == 401


def test_bind_then_read_returns_identity():
    async def run():
        await bind_identity("user-123")
        return authed_user_id()

    assert asyncio.run(run()) == "user-123"


def test_bind_trims_whitespace():
    async def run():
        await bind_identity("  user-456  ")
        return authed_user_id()

    assert asyncio.run(run()) == "user-456"


def test_bind_missing_raises_401():
    async def run():
        await bind_identity(None)

    with pytest.raises(HTTPException) as ei:
        asyncio.run(run())
    assert ei.value.status_code == 401


def test_bind_blank_raises_401():
    async def run():
        await bind_identity("   ")

    with pytest.raises(HTTPException) as ei:
        asyncio.run(run())
    assert ei.value.status_code == 401


def test_require_tenant_returns_value():
    assert require_tenant("tenant-1") == "tenant-1"


def test_require_tenant_missing_raises_400():
    with pytest.raises(HTTPException) as ei:
        require_tenant(None)
    assert ei.value.status_code == 400
