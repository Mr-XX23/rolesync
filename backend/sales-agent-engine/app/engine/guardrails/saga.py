"""Saga compensation (implementation-plan §8): undo completed actions, most recent first.

As decided for this build, nothing is reversed without the rep's OK. Undoing is itself a gated
write, ``undo_actions``, whose approval card lists exactly what would be undone and what
can't be (a sent email cannot be unsent). The orchestrator proposes it when an action fails
after others in the same request succeeded; the model may also propose it when the rep asks.

Every step is reversed by its own tool's undo handler, from the plan that handler recorded
when the action ran (never from model input), and ends COMPENSATED or COMPENSATION_FAILED
with an audit row of its own (``undo:<tool>``).
"""

from __future__ import annotations

import logging
import time
from typing import Any
from uuid import UUID

from pydantic import Field

from app.core.context import AgentContext
from app.core.enums import SagaStatus, ToolOutcome
from app.db.models import SagaStep
from app.db.repositories.ledger import AuditFields, LedgerRepository, StepRecord
from app.platform.langgraph_runtime import is_control_flow_signal
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolDefinition, ToolRegistry
from app.tools.types import (
    ToolCategory,
    ToolFailed,
    ToolInput,
    ToolInputError,
    ToolInvocation,
    ToolKind,
    ToolOutput,
    ToolScope,
    UndoInvocation,
)

logger = logging.getLogger(__name__)

UNDO_TOOL = "undo_actions"


class UndoActionsArgs(ToolInput):
    action_ids: list[UUID] = Field(
        min_length=1, max_length=25, description="The action_id of each completed action to undo (from its result)"
    )
    reason: str = Field(default="", max_length=500, description="Why, in a few words, for the rep")


class Compensator:
    def __init__(self, *, ledger: LedgerRepository, registry: ToolRegistry, executor: ToolExecutor) -> None:
        self._ledger = ledger
        self._registry = registry
        self._executor = executor

    async def undoable_in_turn(self, ctx: AgentContext) -> list[SagaStep]:
        """Completed, reversible actions of the session's current request, oldest first."""
        return await self._ledger.undoable_steps(tenant_id=ctx.tenant_id, session_id=ctx.session_id, turn=ctx.turn)

    def tool(self) -> ToolDefinition:
        return ToolDefinition(
            name=UNDO_TOOL,
            description=(
                "Undo actions you completed earlier in this session, most recent first: cancel a calendar event, "
                "delete a Slack message, move a created document or Notion page to the trash, restore catalog "
                "values or stock, release reserved stock. Sent emails can't be undone. The rep approves the exact "
                "list first. Use the action_id from each action's result."
            ),
            kind=ToolKind.WRITE,
            scope=ToolScope.COMPENSATION,
            category=ToolCategory.ACTION,
            input_model=UndoActionsArgs,
            handler=self._undo,
            irreversible=True,  # an undo can't itself be undone
            timeout_seconds=300,  # several undo steps, each with its own timeout and retries
            preview=self._preview,
        )

    async def _preview(self, ctx: AgentContext, args: ToolInput) -> dict[str, Any]:
        assert isinstance(args, UndoActionsArgs)
        selected, irreversible = await self._select(ctx, args)
        return {
            "kind": "undo",
            "reason": args.reason,
            "actions": [
                {
                    "action_id": str(record.step.id),
                    "tool": record.step.action,
                    "label": (record.step.undo_action or {}).get("label"),
                    "summary": record.summary,
                    "done_at": record.step.updated_at,
                }
                for record in selected
            ],
            "cannot_undo": [{"tool": record.step.action, "summary": record.summary} for record in irreversible],
        }

    async def _undo(self, invocation: ToolInvocation) -> ToolOutput:
        args = invocation.args
        assert isinstance(args, UndoActionsArgs)
        ctx = invocation.ctx
        selected, _ = await self._select(ctx, args)  # re-checked: the steps may have changed since the preview
        results: list[dict[str, Any]] = []
        for record in selected:
            results.append(await self._undo_step(invocation, record))

        undone = [item for item in results if item["undone"]]
        failed = [item for item in results if not item["undone"]]
        summary = f"Undid {len(undone)} of {len(results)} action{'s' if len(results) != 1 else ''}"
        if failed:
            summary += "; could not undo: " + "; ".join(f"{item['label']} ({item['detail']})" for item in failed)
        if not undone:
            raise ToolFailed(summary)
        return ToolOutput(data={"results": results}, summary=summary)

    async def _undo_step(self, invocation: ToolInvocation, record: StepRecord) -> dict[str, Any]:
        step = record.step
        undo = step.undo_action or {}
        label = str(undo.get("label") or step.action)
        definition = self._registry.get(str(undo.get("tool")))
        started = time.monotonic()
        try:
            if definition is None or definition.undo_handler is None:
                raise ToolFailed(f"'{undo.get('tool')}' is no longer available")
            detail = await self._executor.run_undo(definition, UndoInvocation(invocation.ctx, dict(undo.get("args") or {})))
            undone, error = True, None
        except Exception as exc:
            if is_control_flow_signal(exc):
                raise
            if not isinstance(exc, ToolFailed | ToolInputError):
                logger.exception("undo of %s (step %s) raised", step.action, step.id)
            undone, error = False, (str(exc) or type(exc).__name__)[:500]
            detail = error

        recorded = await self._ledger.finish_compensation(
            AuditFields(
                tenant_id=invocation.ctx.tenant_id,
                session_id=invocation.ctx.session_id,
                user_id=invocation.ctx.user_id,
                agent=invocation.agent_name,
                tool=f"undo:{step.action}",
                args={"action_id": str(step.id), **dict(undo.get("args") or {})},
                outcome=ToolOutcome.EXECUTED if undone else ToolOutcome.FAILED,
                result_summary=detail,
                pending_action_id=invocation.pending_action_id,
                duration_ms=int((time.monotonic() - started) * 1000),
            ),
            step_id=step.id,
            compensated=undone,
            error=error,
        )
        if not recorded:
            logger.warning("step %s changed while it was being undone", step.id)
        return {"action_id": str(step.id), "label": label, "undone": undone, "detail": detail}

    async def _select(self, ctx: AgentContext, args: UndoActionsArgs) -> tuple[list[StepRecord], list[StepRecord]]:
        """The steps to undo, newest first, and the completed steps of the same requests that
        can't be undone (so the rep sees what will remain)."""
        wanted = list(dict.fromkeys(args.action_ids))
        records = await self._ledger.step_records(tenant_id=ctx.tenant_id, session_id=ctx.session_id, step_ids=wanted)
        by_id = {record.step.id: record for record in records}
        problems: list[str] = []
        for action_id in wanted:
            record = by_id.get(action_id)
            if record is None:
                problems.append(f"{action_id} is not an action of this session")
                continue
            name = record.summary or record.step.action
            if record.step.status == SagaStatus.COMPENSATED:
                problems.append(f"'{name}' was already undone")
            elif record.step.status != SagaStatus.DONE:
                problems.append(f"'{name}' did not complete ({record.step.status.lower()})")
            elif record.step.undo_action is None:
                problems.append(f"'{name}' can't be undone")
        if problems:
            raise ToolInputError("cannot undo: " + "; ".join(problems))

        turns = {record.step.turn for record in records if record.step.turn is not None}
        irreversible = [
            record
            for record in (
                await self._ledger.step_records(tenant_id=ctx.tenant_id, session_id=ctx.session_id, turns=turns)
                if turns
                else []
            )
            if record.step.status == SagaStatus.DONE
            and record.step.undo_action is None
            and record.step.action != UNDO_TOOL
            and record.step.id not in by_id
        ]
        selected = sorted(records, key=lambda record: record.step.step_no, reverse=True)
        return selected, irreversible
