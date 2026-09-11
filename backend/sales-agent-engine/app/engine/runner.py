"""Drives a session's graph: start → (pause for approval → resume)* → done / failed.

Runs execute as background tasks, so the request that starts or resumes one returns at
once and progress reaches the client over the session's SSE stream. State between
segments lives in the Postgres checkpoint, so a resume works in a fresh process.

Liveness: every entry point takes the session's lease *before* marking it RUNNING and the
run releases it only after settling the status. A RUNNING session without a lease is
therefore an orphan (its process died), and a paused session whose approvals are all
decided was never resumed; the maintenance sweep repairs both, whenever they happen.
Workspace records for a status change are always enqueued *before* the change, so a
follow-up run's records can never be delivered ahead of the previous run's.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Coroutine
from typing import Any
from uuid import UUID, uuid4

from app.core.context import AgentContext, RunMode
from app.core.enums import PendingActionStatus, SessionStatus
from app.db.models import AgentSession
from app.db.repositories import PendingActionRepository, SessionRepository
from app.engine.events import EventType, RedisEventChannel, emit_best_effort
from app.engine.leases import Lease, RunLeases
from app.engine.workspace_record import WorkspaceRecorder
from app.observability.tracing import TracingClient
from app.platform.langgraph_runtime import GraphRuntime, RunOutcome, RunStatus

logger = logging.getLogger(__name__)

CONTINUABLE = frozenset({SessionStatus.DONE, SessionStatus.FAILED, SessionStatus.HALTED})


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
        events: RedisEventChannel,
        leases: RunLeases,
        recorder: WorkspaceRecorder,
        tracer: TracingClient,
        sweep_interval_seconds: float = 30.0,
    ) -> None:
        self._runtime = runtime
        self._sessions = sessions
        self._pending = pending_actions
        self._events = events
        self._leases = leases
        self._recorder = recorder
        self._tracer = tracer
        self._sweep_interval = sweep_interval_seconds
        self._tasks: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------------ entry points
    async def start_new(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        mode: RunMode,
        title: str | None,
        graph_input: dict[str, Any],
        user_message: str | None = None,
    ) -> AgentSession:
        session_id = uuid4()
        lease = await self._leases.acquire(session_id)
        if lease is None:  # pragma: no cover - a fresh id cannot be held
            raise RuntimeError("could not lease a new session id")
        try:
            session = await self._sessions.create(
                session_id=session_id, tenant_id=tenant_id, user_id=user_id, mode=mode, title=title
            )
        except BaseException:
            await lease.release()
            raise
        await self._announce(session.id, user_message)
        self._spawn(self._drive(context_for(session), lease, graph_input=graph_input))
        return session

    async def continue_session(
        self, session: AgentSession, graph_input: dict[str, Any], *, user_message: str | None = None
    ) -> AgentSession | None:
        """Start a new turn in a finished session. ``None`` if it is busy or paused."""
        # A run settles its status just before it releases the lease, so a follow-up sent the
        # moment a turn finishes may briefly find the lease still held.
        wait = 2.0 if session.status in CONTINUABLE else 0.0
        lease = await self._leases.acquire(session.id, wait_seconds=wait)
        if lease is None:
            return None
        claimed = await self._sessions.transition(session.id, to=SessionStatus.RUNNING, expected=CONTINUABLE)
        if claimed is None:
            await lease.release()
            return None
        await self._announce(session.id, user_message)
        self._spawn(self._drive(context_for(claimed), lease, graph_input=graph_input))
        return claimed

    async def resume(self, ctx: AgentContext, decision: dict[str, Any]) -> asyncio.Task[None] | None:
        """Continue a session paused on the decided action. Returns the task that will run it,
        or ``None`` if the session is not paused on that action (already resumed, or paused
        on a different one)."""
        lease = await self._leases.acquire(ctx.session_id)
        if lease is None:
            # The run that paused may still be settling. It checks for decisions before it
            # releases its lease; retrying until the lease is free closes the remaining gap.
            return self._spawn(self._resume_when_free(ctx, decision))
        return await self._claim_and_resume(ctx, lease, decision)

    async def snapshot(self, ctx: AgentContext, *, checkpoint_id: str | None = None) -> RunOutcome:
        return await self._runtime.inspect(ctx, checkpoint_id=checkpoint_id)

    # ------------------------------------------------------------------ maintenance
    async def run_maintenance(self) -> None:
        while True:
            try:
                await self.sweep()
            except Exception:
                logger.exception("maintenance sweep failed")
            await asyncio.sleep(self._sweep_interval)

    async def sweep(self) -> dict[str, list[UUID]]:
        return {"recovered": await self.recover_orphans(), "resumed": await self.resume_stalled_approvals()}

    async def recover_orphans(self) -> list[UUID]:
        """Resume RUNNING sessions whose run died (no lease) from their last checkpoint."""
        recovered: list[UUID] = []
        for listed in await self._sessions.list_by_status(SessionStatus.RUNNING):
            if await self._leases.is_held(listed.id):
                continue
            lease = await self._leases.acquire(listed.id)
            if lease is None:
                continue
            session = await self._sessions.get(listed.id)  # re-read under the lease
            if session is None or session.status != SessionStatus.RUNNING:
                await lease.release()
                continue
            ctx = context_for(session)
            if (await self._runtime.inspect(ctx)).checkpoint_id is None:
                try:
                    await self._fail(ctx, session.title, "the run stopped before it started; please send the message again")
                finally:
                    await lease.release()
                continue
            logger.info("recovering orphaned session %s", session.id)
            self._spawn(self._drive(ctx, lease))
            recovered.append(session.id)
        return recovered

    async def resume_stalled_approvals(self) -> list[UUID]:
        """Resume paused sessions whose approvals were all decided but never resumed (for
        example, the process died right after a reviewer's decision was saved)."""
        resumed: list[UUID] = []
        for session in await self._sessions.list_by_status(SessionStatus.AWAITING_APPROVAL):
            if await self._leases.is_held(session.id):
                continue
            decided = await self._pending.latest_decision_if_settled(tenant_id=session.tenant_id, session_id=session.id)
            if decided is None:
                continue
            decision = {"pending_action_id": str(decided.id), "status": decided.status}
            if await self.resume(context_for(session), decision) is not None:
                resumed.append(session.id)
        return resumed

    async def aclose(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    # ------------------------------------------------------------------ internals
    def _spawn(self, coro: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _announce(self, session_id: UUID, user_message: str | None) -> None:
        # Emitted before the run starts so the stream shows the prompt ahead of the reply.
        if user_message:
            await emit_best_effort(self._events, session_id, EventType.USER_MESSAGE, {"text": user_message})

    async def _resume_when_free(self, ctx: AgentContext, decision: dict[str, Any]) -> None:
        deadline = time.monotonic() + self._leases.ttl_seconds + 5
        while time.monotonic() < deadline:
            await asyncio.sleep(0.2)
            lease = await self._leases.acquire(ctx.session_id)
            if lease is None:
                continue
            task = await self._claim_and_resume(ctx, lease, decision, inline=True)
            if task is not None:
                await task
            return

    async def _claim_and_resume(
        self, ctx: AgentContext, lease: Lease, decision: dict[str, Any], *, inline: bool = False
    ) -> asyncio.Task[None] | None:
        paused_on = {
            str(payload.get("pending_action_id"))
            for payload in (await self._runtime.inspect(ctx)).interrupts
            if isinstance(payload, dict)
        }
        if str(decision.get("pending_action_id")) not in paused_on:
            await lease.release()
            return None
        claimed = await self._sessions.transition(
            ctx.session_id, to=SessionStatus.RUNNING, expected={SessionStatus.AWAITING_APPROVAL}
        )
        if claimed is None:
            await lease.release()
            return None
        run = self._drive(ctx, lease, resume=decision)
        if inline:
            await run
            return None
        return self._spawn(run)

    async def _drive(
        self, ctx: AgentContext, lease: Lease, *, graph_input: dict[str, Any] | None = None, resume: Any = None
    ) -> None:
        """Runs segments until the session pauses, finishes or fails. Owns ``lease``."""
        try:
            session = await self._sessions.get(ctx.session_id)
            title = session.title if session is not None else None
            while True:
                # Every segment re-records RUNNING first, so the workspace context exists
                # before any task or note of the segment, however the run was started.
                await self._recorder.session_updated(ctx, title=title, status=SessionStatus.RUNNING)
                outcome = await self._run_segment(ctx, lease, title, graph_input=graph_input, resume=resume)
                if outcome is None:
                    return
                if outcome.status is RunStatus.INTERRUPTED:
                    decision = await self._settle_pause(ctx, outcome, title)
                    if decision is None:
                        return
                    graph_input, resume = None, decision
                    continue
                await self._finish(ctx, outcome, title)
                return
        except asyncio.CancelledError:
            raise
        except Exception:
            # e.g. the database failed while settling. The lease is released below, so the
            # maintenance sweep picks the session up again from its checkpoint.
            logger.exception("run for session %s stopped unexpectedly", ctx.session_id)
        finally:
            await lease.release()

    async def _run_segment(
        self, ctx: AgentContext, lease: Lease, title: str | None, *, graph_input: dict[str, Any] | None, resume: Any
    ) -> RunOutcome | None:
        run: asyncio.Task[RunOutcome] | None = None
        lost: asyncio.Task[bool] | None = None
        try:
            async with self._tracer.span(
                "session-run",
                kind="chain",
                inputs={"input": graph_input, "resume": resume},
                metadata={"session_id": str(ctx.session_id), "tenant_id": str(ctx.tenant_id), "mode": ctx.mode.value},
            ) as span:
                run = asyncio.create_task(self._runtime.run(ctx, graph_input=graph_input, resume=resume))
                lost = asyncio.create_task(lease.lost.wait())
                await asyncio.wait({run, lost}, return_when=asyncio.FIRST_COMPLETED)
                if not run.done():
                    logger.error("session %s lost its lease; stopping this run", ctx.session_id)
                    return None
                outcome = run.result()
                span.set_outputs({"status": outcome.status.value, "final_answer": outcome.values.get("final_answer")})
                return outcome
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("run failed for session %s", ctx.session_id)
            await self._fail(ctx, title, f"{type(exc).__name__}: {exc}"[:500])
            return None
        finally:
            for task in (run, lost):
                if task is not None and not task.done():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await task

    async def _settle_pause(self, ctx: AgentContext, outcome: RunOutcome, title: str | None) -> dict[str, Any] | None:
        """Record the pause and mark the session AWAITING_APPROVAL. Returns a decision to
        resume with at once if a reviewer already decided while the step was pausing."""
        actions = []
        for payload in outcome.interrupts:
            action_id = payload.get("pending_action_id") if isinstance(payload, dict) else None
            action = await self._pending.get(tenant_id=ctx.tenant_id, action_id=UUID(str(action_id))) if action_id else None
            if action is not None:
                actions.append(action)
        await self._recorder.session_updated(ctx, title=title, status=SessionStatus.AWAITING_APPROVAL)
        for action in actions:
            await self._recorder.action_awaiting_approval(ctx, action)

        await self._sessions.transition(
            ctx.session_id,
            to=SessionStatus.AWAITING_APPROVAL,
            expected={SessionStatus.RUNNING},
            checkpoint_ref=outcome.checkpoint_id,
            settled_event_id=await self._events.latest_id(ctx.session_id),
        )
        for action in actions:
            current = await self._pending.get(tenant_id=ctx.tenant_id, action_id=action.id)
            if current is not None and current.status != PendingActionStatus.PENDING:
                reclaimed = await self._sessions.transition(
                    ctx.session_id, to=SessionStatus.RUNNING, expected={SessionStatus.AWAITING_APPROVAL}
                )
                if reclaimed is None:
                    return None
                return {"pending_action_id": str(current.id), "status": current.status}
        return None

    async def _finish(self, ctx: AgentContext, outcome: RunOutcome, title: str | None) -> None:
        answer = str(outcome.values.get("final_answer") or "")
        prompts = [m.get("content") for m in outcome.values.get("messages") or [] if m.get("role") == "user"]
        await self._recorder.session_updated(ctx, title=title, status=SessionStatus.DONE, summary=answer)
        await self._recorder.answer_recorded(ctx, turn=len(prompts), prompt=prompts[-1] if prompts else None, answer=answer)
        await self._sessions.transition(
            ctx.session_id,
            to=SessionStatus.DONE,
            expected={SessionStatus.RUNNING},
            checkpoint_ref=outcome.checkpoint_id,
            settled_event_id=await self._events.latest_id(ctx.session_id),
        )
        await emit_best_effort(
            self._events, ctx.session_id, EventType.DONE, {"final_answer": answer, "checkpoint_id": outcome.checkpoint_id}
        )

    async def _fail(self, ctx: AgentContext, title: str | None, message: str) -> None:
        # The failed segment's events stay after the previous settle point, so a reopened
        # session still shows what happened before the error.
        await self._recorder.session_updated(ctx, title=title, status=SessionStatus.FAILED, summary=message)
        await self._sessions.transition(ctx.session_id, to=SessionStatus.FAILED, expected={SessionStatus.RUNNING})
        await emit_best_effort(self._events, ctx.session_id, EventType.ERROR, {"message": message})
