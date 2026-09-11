"""Per-tenant budgets, enforced before a turn starts (implementation-plan §8).

- concurrency: agent runs in progress per workspace (``SessionRepository.count_running``)
- rate: requests per user per minute
- cost: model tokens per workspace per UTC day (recorded as the orchestrator uses them)

Counters live in Redis so every API instance shares them. Recording usage is best-effort:
a Redis hiccup must never fail the run that used the tokens.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from redis.asyncio import Redis

from app.core.clock import utcnow

logger = logging.getLogger(__name__)

_DAY_SECONDS = 86_400


class BudgetExceeded(Exception):
    """The message is safe to show to the rep."""


class TenantBudgets:
    def __init__(
        self,
        redis: Redis,
        *,
        key_prefix: str,
        turns_per_minute_per_user: int,
        tokens_per_day_per_tenant: int,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._redis = redis
        self._prefix = key_prefix
        self._turns_per_minute = turns_per_minute_per_user
        self._tokens_per_day = tokens_per_day_per_tenant
        self._clock = clock

    async def admit_turn(self, tenant_id: UUID, user_id: UUID) -> None:
        """Raise ``BudgetExceeded`` if this request may not start now (and count it if it may)."""
        now = self._clock()
        if self._tokens_per_day > 0 and await self.tokens_used_today(tenant_id) >= self._tokens_per_day:
            raise BudgetExceeded(
                "this workspace has used its agent budget for today; it resets at midnight UTC"
            )
        if self._turns_per_minute > 0:
            key = f"{self._prefix}:budget:turns:{tenant_id}:{user_id}:{int(now.timestamp()) // 60}"
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.incr(key)
                pipe.expire(key, 120)
                count, _ = await pipe.execute()
            if int(count) > self._turns_per_minute:
                raise BudgetExceeded(
                    f"too many requests: at most {self._turns_per_minute} per minute. Try again in a moment"
                )

    async def record_tokens(self, tenant_id: UUID, tokens: int) -> None:
        if tokens <= 0:
            return
        key = self._tokens_key(tenant_id)
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.incrby(key, tokens)
                pipe.expire(key, 2 * _DAY_SECONDS)
                await pipe.execute()
        except Exception:
            logger.warning("could not record %d tokens for workspace %s", tokens, tenant_id, exc_info=True)

    async def tokens_used_today(self, tenant_id: UUID) -> int:
        value = await self._redis.get(self._tokens_key(tenant_id))
        return int(value or 0)

    def _tokens_key(self, tenant_id: UUID) -> str:
        return f"{self._prefix}:budget:tokens:{tenant_id}:{self._clock().date().isoformat()}"
