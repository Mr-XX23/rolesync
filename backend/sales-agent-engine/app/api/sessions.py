"""Session history for the chat UI: list, and one session's transcript + open approvals.

Sessions are private to the user who started them.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.approvals import PendingActionView
from app.api.deps import ContainerDep, TenantDep
from app.core.enums import PendingActionStatus, SessionStatus
from app.core.errors import NotFound
from app.db.models import AgentSession
from app.engine.runner import context_for
from app.engine.workspace_record import context_id_for

router = APIRouter(tags=["sessions"])


class SessionView(BaseModel):
    id: UUID
    title: str | None
    status: SessionStatus
    mode: str
    started_at: datetime
    ended_at: datetime | None
    workspace_context_id: UUID  # the workspace-service record of this session's work

    @classmethod
    def of(cls, row: AgentSession) -> SessionView:
        return cls(
            id=row.id,
            title=row.title,
            status=SessionStatus(row.status),
            mode=row.mode,
            started_at=row.started_at,
            ended_at=row.ended_at,
            workspace_context_id=context_id_for(row.id),
        )


class TranscriptItem(BaseModel):
    kind: Literal["user", "assistant", "tool_call", "tool_result"]
    text: str | None = None
    tool: str | None = None
    call_id: str | None = None
    args: dict[str, Any] | None = None
    outcome: str | None = None
    summary: str | None = None
    error: str | None = None


class SessionDetail(SessionView):
    transcript: list[TranscriptItem]
    pending_approvals: list[PendingActionView]
    last_event_id: str  # subscribe to events after this id to continue from this snapshot


@router.get("/sessions", response_model=list[SessionView])
async def list_sessions(
    tenant: TenantDep, container: ContainerDep, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[SessionView]:
    rows = await container.sessions.list_for_user(tenant_id=tenant.tenant_id, user_id=tenant.user_id, limit=limit)
    return [SessionView.of(row) for row in rows]


@router.get("/sessions/{session_id}", response_model=SessionDetail)
async def get_session(session_id: UUID, tenant: TenantDep, container: ContainerDep) -> SessionDetail:
    row = await container.sessions.get_owned(tenant_id=tenant.tenant_id, user_id=tenant.user_id, session_id=session_id)
    if row is None:
        raise NotFound("session not found")
    # Read the event cursor before the snapshot: anything newer is replayed, nothing is lost.
    last_event_id = await container.events.latest_id(row.id)
    snapshot = await container.runner.snapshot(context_for(row))
    approvals = await container.pending_actions.list_for_user(
        tenant_id=tenant.tenant_id, user_id=tenant.user_id, status=PendingActionStatus.PENDING, session_id=row.id
    )
    return SessionDetail(
        **SessionView.of(row).model_dump(),
        transcript=transcript_from(snapshot.values.get("messages") or []),
        pending_approvals=[PendingActionView.model_validate(item) for item in approvals],
        last_event_id=last_event_id,
    )


def transcript_from(messages: list[dict[str, Any]]) -> list[TranscriptItem]:
    items: list[TranscriptItem] = []
    for message in messages:
        role = message.get("role")
        if role == "user":
            items.append(TranscriptItem(kind="user", text=message.get("content") or ""))
        elif role == "assistant":
            if message.get("content"):
                items.append(TranscriptItem(kind="assistant", text=message["content"]))
            for call in message.get("tool_calls") or []:
                items.append(
                    TranscriptItem(kind="tool_call", tool=call.get("name"), call_id=call.get("id"), args=call.get("arguments"))
                )
        elif role == "tool":
            try:
                result = json.loads(message.get("content") or "{}")
            except json.JSONDecodeError:
                result = {}
            items.append(
                TranscriptItem(
                    kind="tool_result",
                    tool=message.get("name"),
                    call_id=message.get("tool_call_id"),
                    outcome=result.get("outcome"),
                    summary=result.get("summary"),
                    error=result.get("error"),
                )
            )
    return items
