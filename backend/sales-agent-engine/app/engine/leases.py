"""Run leases: which process is executing a session right now.

A lease is a Redis key with a TTL, kept alive by a heartbeat. Every entry point takes the
lease *before* it marks a session RUNNING and releases it only after the run has settled
the session's status, so "RUNNING with no lease" reliably means the run's process died
and the maintenance sweep may resume it from its checkpoint. A run that loses its lease
(the key expired or was taken over) is told to stop, so two processes never drive one
session at once.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from uuid import UUID, uuid4

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

_RELEASE = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
_REFRESH = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end"


class Lease:
    def __init__(self, redis: Redis, key: str, token: str, ttl_seconds: int) -> None:
        self._redis = redis
        self._key = key
        self._token = token
        self._ttl = ttl_seconds
        self.lost = asyncio.Event()
        self._heartbeat = asyncio.create_task(self._beat())

    async def release(self) -> None:
        self._heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._heartbeat
        try:
            await self._redis.eval(_RELEASE, 1, self._key, self._token)
        except Exception:
            logger.warning("could not release lease %s (it will expire)", self._key, exc_info=True)

    async def _beat(self) -> None:
        confirmed_at = time.monotonic()
        while True:
            await asyncio.sleep(max(0.5, self._ttl / 3))
            try:
                still_ours = await self._redis.eval(_REFRESH, 1, self._key, self._token, self._ttl)
            except Exception:
                logger.warning("lease heartbeat failed for %s", self._key, exc_info=True)
                if time.monotonic() - confirmed_at > self._ttl:
                    self.lost.set()  # the key has certainly expired by now
                    return
                continue
            if not still_ours:
                self.lost.set()
                return
            confirmed_at = time.monotonic()


class RunLeases:
    def __init__(self, redis: Redis, *, key_prefix: str, ttl_seconds: int) -> None:
        self._redis = redis
        self._prefix = key_prefix
        self.ttl_seconds = ttl_seconds

    def _key(self, session_id: UUID) -> str:
        return f"{self._prefix}:lease:{session_id}"

    async def acquire(self, session_id: UUID, *, wait_seconds: float = 0.0) -> Lease | None:
        """The lease for this session, or ``None`` if another run still holds it after
        ``wait_seconds``."""
        key = self._key(session_id)
        token = uuid4().hex
        deadline = time.monotonic() + wait_seconds
        while not await self._redis.set(key, token, nx=True, ex=self.ttl_seconds):
            if time.monotonic() >= deadline:
                return None
            await asyncio.sleep(0.05)
        return Lease(self._redis, key, token, self.ttl_seconds)

    async def is_held(self, session_id: UUID) -> bool:
        return bool(await self._redis.exists(self._key(session_id)))
