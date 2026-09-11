"""Agent work → workspace-service (goals, tasks, notes), as decided for this build:
workspace-service keeps the user-facing record of what the agent did so it can be
retrieved later; the engine keeps what the agent needs to run (checkpoints, approvals,
audit). Mapping:

- a chat session  → a workspace context (``context_type = AGENT_SESSION``, private to its starter)
- a write action  → a task on that context's timeline (AWAITING_APPROVAL → DONE / REJECTED / ...)
- a sent email, a final answer → a note on that context

Records are written to ``agent.workspace_outbox`` and delivered by ``WorkspaceSyncWorker``.
Recording is best-effort by design: it never slows down or fails an agent run.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID, uuid5

from app.core.context import AgentContext
from app.core.enums import SessionStatus, ToolOutcome
from app.db.models import OutboxKind, PendingAction, WorkspaceOutbox
from app.db.repositories.outbox import OutboxItem, OutboxRepository
from app.platform.workspace_client import Delivery, WorkspaceRecordsClient
from app.tools.types import ToolResult

logger = logging.getLogger(__name__)

# Fixed namespace: record ids are derived from engine ids, so every retry targets the same row.
_NAMESPACE = UUID("5d7c6f5e-2f4b-4f0a-9d7b-8f2d3c1a9e61")
CONTEXT_TYPE = "AGENT_SESSION"

_TASK_STATUS = {
    ToolOutcome.EXECUTED: "DONE",
    ToolOutcome.REJECTED: "REJECTED",
    ToolOutcome.EXPIRED: "EXPIRED",
    ToolOutcome.DENIED: "DENIED",
    ToolOutcome.INVALID: "FAILED",
    ToolOutcome.FAILED: "FAILED",
}


def context_id_for(session_id: UUID) -> UUID:
    return uuid5(_NAMESPACE, f"context:{session_id}")


def task_id_for(idempotency_key: str) -> UUID:
    return uuid5(_NAMESPACE, f"task:{idempotency_key}")


def note_id_for(session_id: UUID, label: str) -> UUID:
    return uuid5(_NAMESPACE, f"note:{session_id}:{label}")


def describe_action(tool: str, args: dict[str, Any]) -> tuple[str, str]:
    """(task name, output type) for the workspace timeline."""
    if tool == "send_email":
        recipients = ", ".join(args.get("to") or [])
        return _clip(f"Email to {recipients}: {args.get('subject', '')}", 150), "EMAIL"
    return _clip(tool.replace("_", " ").capitalize(), 150), _clip(tool.upper(), 50)


class WorkspaceRecorder:
    def __init__(self, outbox: OutboxRepository, *, enabled: bool, on_enqueue: Callable[[], None] | None = None) -> None:
        self._outbox = outbox
        self._enabled = enabled
        self._on_enqueue = on_enqueue

    async def session_updated(
        self, ctx: AgentContext, *, title: str | None, status: SessionStatus, summary: str | None = None
    ) -> None:
        payload = {
            "title": _clip(title or "Sales agent session", 150),
            "context_type": CONTEXT_TYPE,
            "summary": _clip(summary, 2000) if summary else None,
            "status": status.value,
        }
        await self._enqueue(ctx, [self._item(ctx, OutboxKind.CONTEXT, context_id_for(ctx.session_id), payload)])

    async def action_awaiting_approval(self, ctx: AgentContext, action: PendingAction) -> None:
        task_name, output_type = describe_action(action.tool, action.args)
        payload = {
            "task_name": task_name,
            "agent_name": action.agent,
            "output_type": output_type,
            "task_status": "AWAITING_APPROVAL",
            "sort_order": _sort_order(action.idempotency_key),
        }
        await self._enqueue(ctx, [self._item(ctx, OutboxKind.TASK, task_id_for(action.idempotency_key), payload)])

    async def action_finished(
        self, ctx: AgentContext, *, idempotency_key: str, agent: str, tool: str, args: dict[str, Any], result: ToolResult
    ) -> None:
        task_name, output_type = describe_action(tool, args)
        items = [
            self._item(
                ctx,
                OutboxKind.TASK,
                task_id_for(idempotency_key),
                {
                    "task_name": task_name,
                    "agent_name": agent,
                    "output_type": output_type,
                    "task_status": _TASK_STATUS.get(result.outcome, "FAILED"),
                    "sort_order": _sort_order(idempotency_key),
                },
            )
        ]
        if tool == "send_email" and result.outcome is ToolOutcome.EXECUTED:
            lines = [f"To: {', '.join(args.get('to') or [])}"]
            if args.get("cc"):
                lines.append(f"Cc: {', '.join(args['cc'])}")
            lines += [f"Subject: {args.get('subject', '')}", "", str(args.get("body", ""))]
            items.append(
                self._item(
                    ctx,
                    OutboxKind.NOTE,
                    note_id_for(ctx.session_id, f"sent:{idempotency_key}"),
                    {"note_title": _clip(f"Sent: {args.get('subject', 'email')}", 150), "note_body": "\n".join(lines)},
                )
            )
        await self._enqueue(ctx, items)

    async def answer_recorded(self, ctx: AgentContext, *, turn: int, prompt: str | None, answer: str) -> None:
        if not answer.strip():
            return
        title = f"Answer: {(prompt or '').strip().splitlines()[0] if prompt and prompt.strip() else 'agent response'}"
        payload = {"note_title": _clip(title, 150), "note_body": answer}
        await self._enqueue(ctx, [self._item(ctx, OutboxKind.NOTE, note_id_for(ctx.session_id, f"answer:{turn}"), payload)])

    def _item(self, ctx: AgentContext, kind: OutboxKind, target_id: UUID, payload: dict[str, Any]) -> OutboxItem:
        return OutboxItem(
            tenant_id=ctx.tenant_id,
            session_id=ctx.session_id,
            user_id=ctx.user_id,
            kind=kind,
            context_id=context_id_for(ctx.session_id),
            target_id=target_id,
            payload=payload,
        )

    async def _enqueue(self, ctx: AgentContext, items: Sequence[OutboxItem]) -> None:
        if not self._enabled:
            return
        try:
            await self._outbox.enqueue(items)
        except Exception:
            logger.warning("could not record workspace items for session %s", ctx.session_id, exc_info=True)
            return
        if self._on_enqueue is not None:
            self._on_enqueue()


class WorkspaceSyncWorker:
    def __init__(
        self, outbox: OutboxRepository, client: WorkspaceRecordsClient, *, interval_seconds: float, max_attempts: int = 20
    ) -> None:
        self._outbox = outbox
        self._client = client
        self._interval = interval_seconds
        self._max_attempts = max_attempts
        self._wake = asyncio.Event()

    def nudge(self) -> None:
        self._wake.set()

    async def run_forever(self) -> None:
        while True:
            try:
                await self.deliver_due()
            except Exception:
                logger.exception("workspace sync pass failed")
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._interval)
            except TimeoutError:
                pass
            self._wake.clear()

    async def deliver_due(self) -> int:
        delivered = 0
        for session_id in await self._outbox.due_sessions():
            delivered += await self._outbox.deliver_session(session_id, self._deliver, max_attempts=self._max_attempts)
        return delivered

    async def _deliver(self, item: WorkspaceOutbox) -> Delivery:
        if item.kind == OutboxKind.CONTEXT:
            return await self._client.put_context(
                user_id=item.user_id, workspace_id=item.tenant_id, context_id=item.context_id, payload=item.payload
            )
        if item.kind == OutboxKind.TASK:
            return await self._client.put_task(
                user_id=item.user_id, context_id=item.context_id, task_id=item.target_id, payload=item.payload
            )
        return await self._client.put_note(
            user_id=item.user_id, context_id=item.context_id, note_id=item.target_id, payload=item.payload
        )


def _sort_order(idempotency_key: str) -> int:
    """Timeline position from the orchestrator's call id (``{position}-{index}-{model id}``)."""
    _, _, call_id = idempotency_key.partition(":")
    match = re.match(r"^(\d+)-(\d+)-", call_id)
    return int(match.group(1)) * 10 + int(match.group(2)) if match else 0


def _clip(value: str | None, limit: int) -> str:
    text = (value or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"
