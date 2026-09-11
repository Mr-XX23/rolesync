"""Single-task entry: ``POST /chat`` starts (or continues) a session and returns at once;
progress streams on ``GET /sessions/{id}/events``."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import ContainerDep, TenantDep
from app.config import API_PREFIX
from app.core.context import RunMode
from app.core.enums import SessionStatus
from app.core.errors import Conflict, NotFound, TooManyRequests
from app.engine.orchestrator import turn_input

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=8000)
    session_id: UUID | None = Field(default=None, description="Continue this session; omit to start a new one")


class ChatAccepted(BaseModel):
    session_id: UUID
    status: SessionStatus
    events_url: str


@router.post("/chat", status_code=status.HTTP_202_ACCEPTED, response_model=ChatAccepted)
async def chat(body: ChatRequest, tenant: TenantDep, container: ContainerDep) -> ChatAccepted:
    text = body.message.strip()
    limit = container.settings.max_concurrent_runs_per_tenant
    if await container.sessions.count_running(tenant.tenant_id) >= limit:
        raise TooManyRequests(f"this workspace already has {limit} agent runs in progress; try again shortly")

    if body.session_id is None:
        session = await container.runner.start_new(
            tenant_id=tenant.tenant_id,
            user_id=tenant.user_id,
            mode=RunMode.INTERACTIVE,
            title=_title(text),
            graph_input=turn_input(text),
            user_message=text,
        )
    else:
        owned = await container.sessions.get_owned(
            tenant_id=tenant.tenant_id, user_id=tenant.user_id, session_id=body.session_id
        )
        if owned is None:
            raise NotFound("session not found")
        claimed = await container.runner.continue_session(owned, turn_input(text), user_message=text)
        if claimed is None:
            raise Conflict("this session is still working or waiting for an approval")
        session = claimed

    return ChatAccepted(
        session_id=session.id, status=SessionStatus.RUNNING, events_url=f"{API_PREFIX}/sessions/{session.id}/events"
    )


def _title(text: str) -> str:
    first_line = text.splitlines()[0].strip() if text else ""
    return first_line[:120] + ("…" if len(first_line) > 120 else "")
