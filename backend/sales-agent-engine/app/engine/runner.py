"""Drives a session's graph: start → (pause for approval → resume)* → done / failed.

Runs execute as background tasks so the HTTP request that starts or resumes one returns
immediately; progress reaches the client over the session's SSE stream. State between
segments lives in the Postgres checkpoint, so a resume works in a fresh process.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any
from uuid import UUID

from app.core.context import AgentContext
from app.core.enums import PendingActionStatus, SessionStatus
from app.db.repositories import PendingActionRepository, SessionRepository
from app.engine.events import EventEmitter, EventType, emit_best_effort
from app.platform.langgraph_runtime import GraphRuntime, RunOutcome, RunStatus

logger = logging.getLogger(__name__)


class SessionRunner:
    def __init__(
        self,
        *,
        runtime: GraphRuntime,
        sessions: SessionRepository,
        pending_actions: PendingActionRepository,
        events: EventEmitter,
    ) -> None:
        self._runtime = runtime
        self._sessions = sessions
        self._pending = pending_actions
        self._events = events
        self._tasks: set[asyncio.Task[None]] = set()

    def start(self, ctx: AgentContext, graph_input: dict[str, Any]) -> asyncio.Task[None]:
        """Run a session that is already marked RUNNING."""
        return self._spawn(self._drive(ctx, graph_input=graph_input))

    async def resume(self, ctx: AgentContext, decision: dict[str, Any]) -> asyncio.Task[None] | None:
        """Continue a paused session. Returns ``None`` if it was not paused: either another
        request already resumed it, or it is still finishing the step that paused (that
        run notices the decision itself, see ``_settle_pause``)."""
        claimed = await self._sessions.transition(
            ctx.session_id, to=SessionStatus.RUNNING, expected={SessionStatus.AWAITING_APPROVAL}
        )
        if claimed is None:
            return None
        return self._spawn(self._drive(ctx, resume=decision))

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
        try:
            outcome = await self._runtime.run(ctx, graph_input=graph_input, resume=resume)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("run failed for session %s", ctx.session_id)
            await self._sessions.transition(ctx.session_id, to=SessionStatus.FAILED, expected={SessionStatus.RUNNING})
            message = f"{type(exc).__name__}: {exc}"[:500]
            await emit_best_effort(self._events, ctx.session_id, EventType.ERROR, {"message": message})
            return

        if outcome.status is RunStatus.INTERRUPTED:
            await self._settle_pause(ctx, outcome)
            return

        await self._sessions.transition(
            ctx.session_id,
            to=SessionStatus.DONE,
            expected={SessionStatus.RUNNING},
            checkpoint_ref=outcome.checkpoint_id,
        )
        await emit_best_effort(self._events, ctx.session_id, EventType.DONE, {"checkpoint_id": outcome.checkpoint_id})

    async def _settle_pause(self, ctx: AgentContext, outcome: RunOutcome) -> None:
        await self._sessions.transition(
            ctx.session_id,
            to=SessionStatus.AWAITING_APPROVAL,
            expected={SessionStatus.RUNNING},
            checkpoint_ref=outcome.checkpoint_id,
        )
        # A reviewer can decide between the awaiting_approval event and the status change
        # above; their resume request was refused because the run still looked RUNNING.
        # Pick the decision up here so the session cannot stall.
        for payload in outcome.interrupts:
            action_id = payload.get("pending_action_id") if isinstance(payload, dict) else None
            if not action_id:
                continue
            action = await self._pending.get(tenant_id=ctx.tenant_id, action_id=UUID(str(action_id)))
            if action is not None and action.status != PendingActionStatus.PENDING:
                await self.resume(ctx, {"pending_action_id": str(action.id), "status": action.status})
                return
