"""Durable pause/resume through LangGraph + the Postgres checkpointer."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from app.core.context import AgentContext, RunMode
from app.core.enums import PendingActionStatus, SessionStatus
from app.engine.events import EventEmitter, EventType
from tests.integration.conftest import all_events, open_session
from tests.support import SideEffects, note_graph, stub_registry

pytestmark = pytest.mark.integration


def _graph_for(container):
    return note_graph(container.gate)


async def test_write_pauses_the_run_and_resumes_in_a_fresh_process(make_container, tenant_id, user_id):
    effects = SideEffects()

    # Process A: start the run; it pauses on the write.
    first = await make_container(registry=stub_registry(effects), graph_factory=_graph_for)
    ctx = await open_session(first, tenant_id, user_id)
    await first.runner.start(ctx, {"outcomes": []})

    session = await first.sessions.get(ctx.session_id)
    assert session.status == SessionStatus.AWAITING_APPROVAL and session.checkpoint_ref
    [pending] = await first.pending_actions.list_for_user(tenant_id=tenant_id, user_id=user_id)
    assert effects.sent == []
    await first.aclose()  # the process "exits" while paused

    # Process B: a new container (new checkpointer pool) approves and resumes.
    second = await make_container(registry=stub_registry(effects), graph_factory=_graph_for)
    await second.pending_actions.resolve(
        tenant_id=tenant_id, action_id=pending.id, status=PendingActionStatus.APPROVED, resolved_by=user_id
    )
    task = await second.runner.resume(ctx, {"pending_action_id": str(pending.id)})
    assert task is not None
    await task

    session = await second.sessions.get(ctx.session_id)
    assert session.status == SessionStatus.DONE and session.ended_at is not None
    assert len(effects.sent) == 1
    [audit] = await second.ledger.list_audit(tenant_id=tenant_id, session_id=ctx.session_id)
    assert audit.outcome == "EXECUTED"
    types = [e["type"] for e in await all_events(second, ctx.session_id)]
    assert types == ["tool_call", "awaiting_approval", "tool_result", "done"]


async def test_second_resume_is_a_no_op(make_container, tenant_id, user_id):
    effects = SideEffects()
    container = await make_container(registry=stub_registry(effects), graph_factory=_graph_for)
    ctx = await open_session(container, tenant_id, user_id)
    await container.runner.start(ctx, {"outcomes": []})
    [pending] = await container.pending_actions.list_for_user(tenant_id=tenant_id, user_id=user_id)
    await container.pending_actions.resolve(
        tenant_id=tenant_id, action_id=pending.id, status=PendingActionStatus.APPROVED, resolved_by=user_id
    )

    task = await container.runner.resume(ctx, {"pending_action_id": str(pending.id)})
    duplicate = await container.runner.resume(ctx, {"pending_action_id": str(pending.id)})
    await task

    assert duplicate is None
    assert len(effects.sent) == 1


async def test_rejection_finishes_the_run_without_side_effects(make_container, tenant_id, user_id):
    effects = SideEffects()
    container = await make_container(registry=stub_registry(effects), graph_factory=_graph_for)
    ctx = await open_session(container, tenant_id, user_id)
    await container.runner.start(ctx, {"outcomes": []})
    [pending] = await container.pending_actions.list_for_user(tenant_id=tenant_id, user_id=user_id)

    await container.pending_actions.resolve(
        tenant_id=tenant_id, action_id=pending.id, status=PendingActionStatus.REJECTED, resolved_by=user_id
    )
    await (await container.runner.resume(ctx, {"pending_action_id": str(pending.id)}))

    assert (await container.sessions.get(ctx.session_id)).status == SessionStatus.DONE
    assert effects.sent == []


class _FastReviewer:
    """Wraps the event channel and approves the instant ``awaiting_approval`` is emitted
    (while the run still looks RUNNING), then asks the runner to resume. That early resume
    is refused, so the runner itself must notice the decision when it records the pause."""

    def __init__(self, inner: EventEmitter, container, tenant_id: UUID, user_id: UUID) -> None:
        self._inner = inner
        self._container = container
        self._tenant_id = tenant_id
        self._user_id = user_id
        self.observations: list[Any] = []

    async def emit(self, session_id, type, data=None):
        entry = await self._inner.emit(session_id, type, data)
        if type is EventType.AWAITING_APPROVAL:
            action_id = UUID(str(data["pending_action_id"]))
            await self._container.pending_actions.resolve(
                tenant_id=self._tenant_id, action_id=action_id, status=PendingActionStatus.APPROVED,
                resolved_by=self._user_id,
            )
            session = await self._container.sessions.get(session_id)
            ctx = AgentContext(
                tenant_id=session.tenant_id, user_id=session.user_id, session_id=session.id, mode=RunMode(session.mode)
            )
            early = await self._container.runner.resume(ctx, {"pending_action_id": str(action_id)})
            self.observations.append((session.status, early))
        return entry


async def test_decision_that_lands_before_the_pause_is_recorded_is_not_lost(make_container, tenant_id, user_id):
    effects = SideEffects()
    container = await make_container(registry=stub_registry(effects), graph_factory=_graph_for)
    reviewer = _FastReviewer(container.events, container, tenant_id, user_id)
    container.gate._events = reviewer  # hook the gate's emission point
    ctx = await open_session(container, tenant_id, user_id)

    await container.runner.start(ctx, {"outcomes": []})
    # _settle_pause saw the decision and spawned the resume; wait for it to finish.
    for task in list(container.runner._tasks):
        await task

    assert reviewer.observations == [(SessionStatus.RUNNING, None)]  # early resume was refused
    assert (await container.sessions.get(ctx.session_id)).status == SessionStatus.DONE
    assert len(effects.sent) == 1
