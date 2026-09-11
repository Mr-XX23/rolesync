"""Durable pause/resume through LangGraph + the Postgres checkpointer, and run liveness."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import pytest

from app.core.context import AgentContext, RunMode
from app.core.enums import PendingActionStatus, SessionStatus
from app.engine.events import EventEmitter, EventType
from app.platform.langgraph_runtime import END, GraphSpec
from tests.integration.conftest import all_events, settle_runs, start_run
from tests.support import NoteState, SideEffects, note_graph, stub_registry

pytestmark = pytest.mark.integration


def _graph_for(container):
    return note_graph(container.gate)


async def test_write_pauses_the_run_and_resumes_in_a_fresh_process(make_container, tenant_id, user_id):
    effects = SideEffects()

    # Process A: start the run; it pauses on the write.
    first = await make_container(registry=stub_registry(effects), graph_factory=_graph_for)
    ctx = await start_run(first, tenant_id, user_id, {"outcomes": []})
    await settle_runs(first)

    session = await first.sessions.get(ctx.session_id)
    assert session.status == SessionStatus.AWAITING_APPROVAL and session.checkpoint_ref
    # The settle position is the last event before the pause, so a snapshot + later events never overlap.
    assert session.settled_event_id == (await first.events.latest_id(ctx.session_id))
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
    ctx = await start_run(container, tenant_id, user_id, {"outcomes": []})
    await settle_runs(container)
    [pending] = await container.pending_actions.list_for_user(tenant_id=tenant_id, user_id=user_id)
    await container.pending_actions.resolve(
        tenant_id=tenant_id, action_id=pending.id, status=PendingActionStatus.APPROVED, resolved_by=user_id
    )

    await container.runner.resume(ctx, {"pending_action_id": str(pending.id)})
    # The first resume holds the lease, so this one waits for it, then finds nothing paused.
    await container.runner.resume(ctx, {"pending_action_id": str(pending.id)})
    await settle_runs(container)

    assert (await container.sessions.get(ctx.session_id)).status == SessionStatus.DONE
    assert len(effects.sent) == 1
    # Once the run is over, a late resume is refused outright.
    assert await container.runner.resume(ctx, {"pending_action_id": str(pending.id)}) is None


async def test_rejection_finishes_the_run_without_side_effects(make_container, tenant_id, user_id):
    effects = SideEffects()
    container = await make_container(registry=stub_registry(effects), graph_factory=_graph_for)
    ctx = await start_run(container, tenant_id, user_id, {"outcomes": []})
    await settle_runs(container)
    [pending] = await container.pending_actions.list_for_user(tenant_id=tenant_id, user_id=user_id)

    await container.pending_actions.resolve(
        tenant_id=tenant_id, action_id=pending.id, status=PendingActionStatus.REJECTED, resolved_by=user_id
    )
    await (await container.runner.resume(ctx, {"pending_action_id": str(pending.id)}))

    assert (await container.sessions.get(ctx.session_id)).status == SessionStatus.DONE
    assert effects.sent == []


class _FastReviewer:
    """Wraps the event channel and approves the instant ``awaiting_approval`` is emitted
    (while the run still holds its lease and looks RUNNING), then asks the runner to resume.
    That resume can only wait, so the run itself must notice the decision when it settles."""

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
            self.observations.append((session.status, early is not None))
        return entry


async def test_decision_that_lands_before_the_pause_is_recorded_is_not_lost(make_container, tenant_id, user_id):
    effects = SideEffects()
    container = await make_container(registry=stub_registry(effects), graph_factory=_graph_for)
    reviewer = _FastReviewer(container.events, container, tenant_id, user_id)
    container.gate._events = reviewer  # hook the gate's emission point

    ctx = await start_run(container, tenant_id, user_id, {"outcomes": []})
    await settle_runs(container)

    assert reviewer.observations == [(SessionStatus.RUNNING, True)]  # the early resume had to wait
    assert (await container.sessions.get(ctx.session_id)).status == SessionStatus.DONE
    assert len(effects.sent) == 1


async def test_a_decision_that_was_never_resumed_is_picked_up_by_the_sweep(make_container, tenant_id, user_id):
    effects = SideEffects()
    container = await make_container(registry=stub_registry(effects), graph_factory=_graph_for)
    ctx = await start_run(container, tenant_id, user_id, {"outcomes": []})
    await settle_runs(container)
    assert await container.runner.sweep() == {"expired": [], "recovered": [], "resumed": []}  # still waiting on a human

    # The decision was saved, but the process died before it resumed the run.
    [pending] = await container.pending_actions.list_for_user(tenant_id=tenant_id, user_id=user_id)
    await container.pending_actions.resolve(
        tenant_id=tenant_id, action_id=pending.id, status=PendingActionStatus.APPROVED, resolved_by=user_id
    )
    swept = await container.runner.sweep()
    await settle_runs(container)

    assert swept == {"expired": [], "recovered": [], "resumed": [ctx.session_id]}
    assert (await container.sessions.get(ctx.session_id)).status == SessionStatus.DONE
    assert len(effects.sent) == 1
    assert await container.runner.sweep() == {"expired": [], "recovered": [], "resumed": []}


async def test_an_orphan_that_never_reached_a_checkpoint_fails_with_a_clear_message(make_container, tenant_id, user_id):
    container = await make_container(graph_factory=_graph_for)
    # RUNNING with no lease and no checkpoint: its process died before the graph started.
    row = await container.sessions.create(tenant_id=tenant_id, user_id=user_id, mode=RunMode.INTERACTIVE, title="hi")

    assert await container.runner.recover_orphans() == []

    assert (await container.sessions.get(row.id)).status == SessionStatus.FAILED
    [error] = [e for e in await all_events(container, row.id) if e["type"] == "error"]
    assert "please send the message again" in error["data"]["message"]


def _blocking_graph(started: asyncio.Event) -> GraphSpec:
    async def act(state: dict[str, Any]) -> dict[str, Any]:
        started.set()
        await asyncio.Event().wait()
        return {}  # pragma: no cover

    return GraphSpec(state_schema=NoteState, nodes={"act": act}, entry="act", edges=[("act", END)])


async def test_a_run_that_loses_its_lease_stops_and_leaves_the_session_to_the_new_owner(
    make_container, tenant_id, user_id
):
    started = asyncio.Event()
    container = await make_container(
        graph_factory=lambda _: _blocking_graph(started), settings_overrides={"run_lease_seconds": 1}
    )
    ctx = await start_run(container, tenant_id, user_id, {"outcomes": []})
    await asyncio.wait_for(started.wait(), 10)

    # Another process took the session over (say this one stalled past the lease's TTL).
    key = container.leases._key(ctx.session_id)
    await container.redis.set(key, "another-process")
    await settle_runs(container, timeout=10)  # the next heartbeat notices and the run stops

    assert await container.redis.get(key) == "another-process"  # its lease is left alone
    assert (await container.sessions.get(ctx.session_id)).status == SessionStatus.RUNNING  # and so is the session
