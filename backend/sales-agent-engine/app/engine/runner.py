"""Drives a session's graph: start → (pause for approval → resume)* → done / failed.

Runs execute as background tasks, so the request that starts or resumes one returns at
once and progress reaches the client over the session's SSE stream. State between
segments lives in the Postgres checkpoint, so a resume works in a fresh process, and a
run whose process died mid-step (RUNNING with no lease) is picked up by recovery.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from datetime import timedelta
from typing import Any
from uuid import UUID

from app.core.clock import utcnow
from app.core.context import AgentContext, RunMode
from app.core.enums import PendingActionStatus, SessionStatus
from app.db.models import AgentSession
from app.db.repositories import PendingActionRepository, SessionRepository
from app.engine.events import EventEmitter, EventType, emit_best_effort
from app.engine.leases import LeaseHeld, RunLeases
from app.engine.workspace_record import WorkspaceRecorder
from app.observability.tracing import TracingClient
from app.platform.langgraph_runtime import GraphRuntime, RunOutcome, RunStatus

logger = logging.getLogger(__name__)


def context_for(session: AgentSession) -> AgentContext:
    """Rebuild a run's identity from its persisted session row (never from client input)."""
    return AgentContext(
        tenant_id=session.tenant_id,
        user_id=session.user_id,
        session_id=session.id,
        mode=RunMode(session.mode),
        goal_id=session.goal_id,
    )


class SessionRunner:
    def __init__(
        self,
        *,
        runtime: GraphRuntime,
        sessions: SessionRepository,
        pending_actions: PendingActionRepository,
        events: EventEmitter,
        leases: RunLeases,
        recorder: WorkspaceRecorder,
        tracer: TracingClient,
    ) -> None:
        self._runtime = runtime
        self._sessions = sessions
        self._pending = pending_actions
        self._events = events
        self._leases = leases
        self._recorder = recorder
        self._tracer = tracer
        self._tasks: set[asyncio.Task[None]] = set()

    def start(self, ctx: AgentContext, graph_input: dict[str, Any]) -> asyncio.Task[None]:
        """Run a turn for a session that is already marked RUNNING."""
        return self._spawn(self._drive(ctx, graph_input=graph_input))

    async def resume(self, ctx: AgentContext, decision: dict[str, Any]) -> asyncio.Task[None] | None:
        """Continue a paused session. Returns ``None`` if it was not paused: another request
        already resumed it, or it is still finishing the step that paused (that run notices
        the decision itself, see ``_settle_pause``)."""
        claimed = await self._sessions.transition(
            ctx.session_id, to=SessionStatus.RUNNING, expected={SessionStatus.AWAITING_APPROVAL}
        )
        if claimed is None:
            return None
        return self._spawn(self._drive(ctx, resume=decision))

    async def recover_orphans(self, *, idle_seconds: float) -> list[UUID]:
        """Resume RUNNING sessions whose process died (no live lease) from their checkpoint.

        Only sessions idle for ``idle_seconds`` are considered, so a session another instance
        created a moment ago (lease not acquired yet) is never mistaken for an orphan."""
        recovered: list[UUID] = []
        cutoff = utcnow() - timedelta(seconds=idle_seconds)
        for session in await self._sessions.list_by_status(SessionStatus.RUNNING, updated_before=cutoff):
            if await self._leases.is_held(session.id):
                continue
            ctx = context_for(session)
            snapshot = await self._runtime.inspect(ctx)
            if snapshot.checkpoint_id is None:
                message = "the run was interrupted before it started; send the message again"
                await self._fail(ctx, message)
                continue
            logger.info("recovering orphaned session %s", session.id)
            self._spawn(self._drive(ctx))
            recovered.append(session.id)
        return recovered

    async def snapshot(self, ctx: AgentContext) -> RunOutcome:
        return await self._runtime.inspect(ctx)

    async def aclose(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _drive(self, ctx: AgentContext, *, graph_input: dict[str, Any] | None = None, resume: Any = None) -> None:
        session = await self._sessions.get(ctx.session_id)
        title = session.title if session is not None else None
        # Recorded at the start of every segment, so the workspace context always exists
        # before any task or note of this segment, however the run was started.
        await self._recorder.session_updated(ctx, title=title, status=SessionStatus.RUNNING)
        try:
            async with self._leases.hold(ctx.session_id):
                async with self._tracer.span(
                    "session-run",
                    kind="chain",
                    inputs={"input": graph_input, "resume": resume},
                    metadata={"session_id": str(ctx.session_id), "tenant_id": str(ctx.tenant_id), "mode": ctx.mode.value},
                ) as span:
                    outcome = await self._runtime.run(ctx, graph_input=graph_input, resume=resume)
                    span.set_outputs({"status": outcome.status.value, "final_answer": outcome.values.get("final_answer")})
        except LeaseHeld:
            logger.info("session %s is already being run by another worker", ctx.session_id)
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("run failed for session %s", ctx.session_id)
            await self._fail(ctx, f"{type(exc).__name__}: {exc}"[:500])
            return

        if outcome.status is RunStatus.INTERRUPTED:
            await self._settle_pause(ctx, outcome, title)
            return

        await self._sessions.transition(
            ctx.session_id, to=SessionStatus.DONE, expected={SessionStatus.RUNNING}, checkpoint_ref=outcome.checkpoint_id
        )
        answer = str(outcome.values.get("final_answer") or "")
        await emit_best_effort(
            self._events, ctx.session_id, EventType.DONE, {"final_answer": answer, "checkpoint_id": outcome.checkpoint_id}
        )
        await self._recorder.session_updated(ctx, title=title, status=SessionStatus.DONE, summary=answer)
        prompts = [m.get("content") for m in outcome.values.get("messages") or [] if m.get("role") == "user"]
        await self._recorder.answer_recorded(ctx, turn=len(prompts), prompt=prompts[-1] if prompts else None, answer=answer)

    async def _settle_pause(self, ctx: AgentContext, outcome: RunOutcome, title: str | None) -> None:
        actions = []
        for payload in outcome.interrupts:
            action_id = payload.get("pending_action_id") if isinstance(payload, dict) else None
            action = await self._pending.get(tenant_id=ctx.tenant_id, action_id=UUID(str(action_id))) if action_id else None
            if action is not None:
                actions.append(action)
        # Record the pause before the session becomes resumable: once it is AWAITING_APPROVAL a
        # reviewer can resume it, and that run's DONE records must land after these.
        await self._recorder.session_updated(ctx, title=title, status=SessionStatus.AWAITING_APPROVAL)
        for action in actions:
            await self._recorder.action_awaiting_approval(ctx, action)

        await self._sessions.transition(
            ctx.session_id,
            to=SessionStatus.AWAITING_APPROVAL,
            expected={SessionStatus.RUNNING},
            checkpoint_ref=outcome.checkpoint_id,
        )
        for action in actions:
            # A reviewer can decide between the awaiting_approval event and the status change
            # above; their resume request was refused because the run still looked RUNNING.
            # Pick the decision up here so the session cannot stall.
            current = await self._pending.get(tenant_id=ctx.tenant_id, action_id=action.id)
            if current is not None and current.status != PendingActionStatus.PENDING:
                await self.resume(ctx, {"pending_action_id": str(current.id), "status": current.status})
                return

    async def _fail(self, ctx: AgentContext, message: str) -> None:
        row = await self._sessions.transition(ctx.session_id, to=SessionStatus.FAILED, expected={SessionStatus.RUNNING})
        await emit_best_effort(self._events, ctx.session_id, EventType.ERROR, {"message": message})
        if row is not None:
            await self._recorder.session_updated(ctx, title=row.title, status=SessionStatus.FAILED, summary=message)
