from __future__ import annotations

from redis.asyncio import Redis

from app.config import Settings


def create_redis(settings: Settings) -> Redis:
    return Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        decode_responses=True,
        health_check_interval=30,
    )
