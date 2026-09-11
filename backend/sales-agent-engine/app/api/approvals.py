"""Human-in-the-loop decisions: approve / edit / reject a pending action (§9)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.api.deps import ContainerDep, TenantDep
from app.core.enums import PendingActionStatus
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.engine.events import EventType, emit_best_effort
from app.engine.runner import context_for
from app.tools.types import describe_validation_error

router = APIRouter(tags=["approvals"])
logger = logging.getLogger(__name__)

_STATUS_FOR_DECISION = {
    "approve": PendingActionStatus.APPROVED,
    "edit": PendingActionStatus.EDITED,
    "reject": PendingActionStatus.REJECTED,
}


class PendingActionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    agent: str
    tool: str
    args: dict[str, Any]
    edited_args: dict[str, Any] | None
    preview: dict[str, Any]
    status: PendingActionStatus
    expires_at: datetime
    resolved_by: UUID | None
    resolved_at: datetime | None
    decision_note: str | None
    created_at: datetime


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "edit", "reject"]
    args: dict[str, Any] | None = Field(default=None, description="Replacement arguments; required for 'edit'")
    note: str | None = Field(default=None, max_length=2000)


@router.get("/approvals", response_model=list[PendingActionView])
async def list_approvals(
    tenant: TenantDep,
    container: ContainerDep,
    status: PendingActionStatus | None = PendingActionStatus.PENDING,
    session_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[Any]:
    return await container.pending_actions.list_for_user(
        tenant_id=tenant.tenant_id, user_id=tenant.user_id, status=status, session_id=session_id, limit=limit
    )


@router.post("/approvals/{action_id}/decision", response_model=PendingActionView)
async def decide(action_id: UUID, body: DecisionRequest, tenant: TenantDep, container: ContainerDep) -> Any:
    action = await container.pending_actions.get(tenant_id=tenant.tenant_id, action_id=action_id)
    session = await container.sessions.get(action.session_id) if action is not None else None
    if action is None or session is None or session.user_id != tenant.user_id:
        raise NotFound("approval not found")
    if action.status != PendingActionStatus.PENDING:
        raise Conflict(f"approval is already {action.status.lower()}")

    edited_args: dict[str, Any] | None = None
    if body.decision == "edit":
        if body.args is None:
            raise ValidationFailed("'args' is required when the decision is 'edit'")
        definition = container.registry.get(action.tool)
        if definition is None:
            raise Conflict(f"tool '{action.tool}' is no longer available")
        try:
            edited_args = definition.input_model.model_validate(body.args).model_dump(mode="json")
        except ValidationError as exc:
            raise ValidationFailed(f"edited arguments are invalid: {describe_validation_error(exc)}") from exc

    resolved = await container.pending_actions.resolve(
        tenant_id=tenant.tenant_id,
        action_id=action.id,
        status=_STATUS_FOR_DECISION[body.decision],
        resolved_by=tenant.user_id,
        edited_args=edited_args,
        note=body.note,
    )
    if resolved is None:
        raise Conflict("approval is no longer pending (already decided or expired)")

    await emit_best_effort(
        container.events,
        session.id,
        EventType.APPROVAL_RESOLVED,
        {"pending_action_id": resolved.id, "status": resolved.status, "resolved_by": tenant.user_id},
    )
    try:
        await container.runner.resume(context_for(session), {"pending_action_id": str(resolved.id), "status": resolved.status})
    except Exception:
        # The decision is saved; the maintenance sweep resumes decided-but-paused sessions.
        logger.exception("could not resume session %s after a decision", session.id)
    return resolved
