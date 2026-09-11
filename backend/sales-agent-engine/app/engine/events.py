"""Event emitter → per-session Redis stream → SSE (implementation-plan §9).

Every event uses the plan's envelope ``{type, session_id, data, ts}``. Streams live in
Redis so any process (API or autonomy worker) can emit and any API instance can
serve the SSE connection; the stream entry id doubles as the SSE ``id`` so a client
that reconnects with ``Last-Event-ID`` resumes exactly where it left off.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from pydantic_core import to_jsonable_python
from redis.asyncio import Redis

from app.core.clock import utcnow

logger = logging.getLogger(__name__)


class EventType(StrEnum):
    STEP_STARTED = "step_started"
    TOKEN = "token"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVAL_RESOLVED = "approval_resolved"  # addition: lets every open client update its approval card
    PROGRESS = "progress"
    DONE = "done"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class StreamedEvent:
    id: str
    envelope: dict[str, Any]


class EventEmitter(Protocol):
    async def emit(self, session_id: UUID, type: EventType, data: Mapping[str, Any] | None = None) -> str: ...


async def emit_best_effort(
    emitter: EventEmitter, session_id: UUID, type: EventType, data: Mapping[str, Any] | None = None
) -> None:
    """Events feed the live UI; the database stays the source of truth, so a stream
    hiccup must never fail (or double-run) the work that produced the event."""
    try:
        await emitter.emit(session_id, type, data)
    except Exception:
        logger.warning("could not emit %s for session %s", type.value, session_id, exc_info=True)


class RedisEventChannel:
    def __init__(self, redis: Redis, *, key_prefix: str, maxlen: int, ttl_seconds: int) -> None:
        self._redis = redis
        self._prefix = key_prefix
        self._maxlen = maxlen
        self._ttl = ttl_seconds

    def _key(self, session_id: UUID) -> str:
        return f"{self._prefix}:events:{session_id}"

    async def emit(self, session_id: UUID, type: EventType, data: Mapping[str, Any] | None = None) -> str:
        envelope = {
            "type": type.value,
            "session_id": str(session_id),
            "data": to_jsonable_python(dict(data or {})),
            "ts": utcnow().isoformat(),
        }
        key = self._key(session_id)
        async with self._redis.pipeline(transaction=False) as pipe:
            pipe.xadd(key, {"e": json.dumps(envelope)}, maxlen=self._maxlen, approximate=True)
            pipe.expire(key, self._ttl)
            entry_id, _ = await pipe.execute()
        return _text(entry_id)

    async def read(
        self, session_id: UUID, *, after: str, block_ms: int | None = None, count: int = 100
    ) -> list[StreamedEvent]:
        """Events strictly after stream id ``after`` (``"0-0"`` = from the beginning)."""
        response = await self._redis.xread({self._key(session_id): after}, count=count, block=block_ms)
        return [
            StreamedEvent(id=_text(entry_id), envelope=json.loads(_text(fields["e"])))
            for entry_id, fields in _entries(response)
        ]


def _entries(response: Any) -> list[tuple[Any, dict[str, Any]]]:
    # RESP2 → [[key, [(id, fields), ...]]]; RESP3 → {key: [[id, fields], ...]}
    if not response:
        return []
    streams = response.values() if isinstance(response, dict) else (entries for _, entries in response)
    return [(entry[0], entry[1]) for entries in streams for entry in entries]


def _text(value: Any) -> str:
    # The client is created with decode_responses=True; ids may still arrive as bytes via RESP3 maps.
    return value.decode() if isinstance(value, bytes) else str(value)
