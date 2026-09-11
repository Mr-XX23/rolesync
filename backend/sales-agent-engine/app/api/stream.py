"""SSE channel: ``GET /sessions/{id}/events`` (implementation-plan §9).

Browsers' ``EventSource`` cannot send custom headers, so the tenant is taken from the
session row (then membership is re-checked) instead of ``X-Tenant-Id``. Reconnects
resume after ``Last-Event-ID`` (or ``?last_event_id=``); a first connect replays the
retained history so a reopened chat can rebuild its timeline.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request
from sse_starlette.sse import EventSourceResponse, ServerSentEvent

from app.api.deps import ContainerDep, PrincipalDep
from app.core.errors import BadRequest, NotFound

router = APIRouter(tags=["stream"])

_STREAM_ID = re.compile(r"\d+-\d+")


@router.get("/sessions/{session_id}/events")
async def session_events(
    session_id: UUID,
    request: Request,
    principal: PrincipalDep,
    container: ContainerDep,
    last_event_id: Annotated[str | None, Query()] = None,
) -> EventSourceResponse:
    session = await container.sessions.get(session_id)
    if session is None or session.user_id != principal.user_id:
        raise NotFound("session not found")
    await container.workspaces.require_member(principal.user_id, session.tenant_id)

    cursor = request.headers.get("last-event-id") or last_event_id or "0-0"
    if not _STREAM_ID.fullmatch(cursor):
        raise BadRequest("Last-Event-ID must be a stream id like 1726000000000-0")

    settings = container.settings
    channel = container.events

    async def publish() -> AsyncIterator[ServerSentEvent]:
        position = cursor
        deadline = time.monotonic() + settings.sse_max_connection_seconds
        while time.monotonic() < deadline:
            for event in await channel.read(session_id, after=position, block_ms=settings.sse_ping_seconds * 1000):
                position = event.id
                yield ServerSentEvent(data=json.dumps(event.envelope), id=event.id)

    return EventSourceResponse(
        publish(),
        ping=settings.sse_ping_seconds,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
