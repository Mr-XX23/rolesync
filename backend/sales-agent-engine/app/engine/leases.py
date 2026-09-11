"""Run leases: which process is executing a session right now.

A lease is a Redis key with a TTL, refreshed by a heartbeat while the run executes. It
stops two processes from driving one session at once, and a RUNNING session without a
lease is an orphan (its process died) that recovery may resume from the checkpoint.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

_RELEASE = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
_REFRESH = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end"


class LeaseHeld(Exception):
    """Another process is already executing this session."""


class RunLeases:
    def __init__(self, redis: Redis, *, key_prefix: str, ttl_seconds: int) -> None:
        self._redis = redis
        self._prefix = key_prefix
        self._ttl = ttl_seconds

    def _key(self, session_id: UUID) -> str:
        return f"{self._prefix}:lease:{session_id}"

    async def is_held(self, session_id: UUID) -> bool:
        return bool(await self._redis.exists(self._key(session_id)))

    @contextlib.asynccontextmanager
    async def hold(self, session_id: UUID) -> AsyncIterator[None]:
        key = self._key(session_id)
        token = uuid4().hex
        if not await self._redis.set(key, token, nx=True, ex=self._ttl):
            raise LeaseHeld(str(session_id))
        heartbeat = asyncio.create_task(self._heartbeat(key, token))
        try:
            yield
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat
            try:
                await self._redis.eval(_RELEASE, 1, key, token)
            except Exception:
                logger.warning("could not release lease for session %s (it will expire)", session_id, exc_info=True)

    async def _heartbeat(self, key: str, token: str) -> None:
        while True:
            await asyncio.sleep(max(1.0, self._ttl / 3))
            try:
                await self._redis.eval(_REFRESH, 1, key, token, self._ttl)
            except Exception:
                logger.warning("lease heartbeat failed for %s", key, exc_info=True)
