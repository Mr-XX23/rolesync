"""THE choke point: every tool call from every agent goes through ``ToolGate.call_tool``.

Pipeline (implementation-plan §4):
 1. tenant + user come from the server-built ``AgentContext``, never from arguments
 2. per-agent scope check (``registry.SCOPES``)
 3. argument validation, then the tool's resource ACL
 4. WRITE only:
    - already executed under this idempotency key → return the prior result
    - INTERACTIVE → preview + ``pending_action`` + ``awaiting_approval`` event + durable pause
    - AUTONOMOUS  → autonomy policy: inside the envelope → act; outside → the same human path
    - saga step recorded *before* the side effect (with the request's turn); how to undo it is
      recorded with the result, since only the handler knows what it created
 5. execute under the executor (timeout, retries for transient read failures, circuit breaker)
 6. an ``agent.audit`` row for every outcome, including refusals
 7. the result goes back to the calling agent

Re-execution: a graph node that resumes after an approval runs again from the top, so
everything before the pause is a lookup keyed by ``{session_id}:{call_id}``. What runs after
an approval is exactly what was approved: the stored arguments, or the reviewer's edit.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Protocol
from uuid import UUID

from pydantic import ValidationError
from pydantic_core import to_jsonable_python

from app.autonomy.policy import AutonomyPolicy, PolicyDecision, Verdict
from app.core.clock import utcnow
from app.core.context import AgentContext, RunMode
from app.core.enums import PendingActionStatus, SagaStatus, ToolOutcome
from app.db.repositories import LedgerRepository, PendingActionRepository
from app.db.repositories.ledger import AuditFields
from app.engine.events import EventEmitter, EventType, emit_best_effort
from app.observability.tracing import TracingClient
from app.platform.langgraph_runtime import is_control_flow_signal
from app.tools.executor import ToolExecutor
from app.tools.registry import AgentScopes, ToolDefinition, ToolRegistry
from app.tools.types import (
    SourceLink,
    ToolAccessDenied,
    ToolFailed,
    ToolInput,
    ToolInputError,
    ToolInvocation,
    ToolKind,
    ToolOutcomeUnknown,
    ToolResult,
    describe_validation_error,
)

logger = logging.getLogger(__name__)

# Identity is attached by the platform. A model that tries to pass it as an argument is refused.
_IDENTITY_ARGS = frozenset({"tenant_id", "user_id", "workspace_id", "session_id"})


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    tenant_id: UUID
    session_id: UUID
    pending_action_id: UUID
    tool: str
    call_id: str


class ApprovalPort(Protocol):
    """Pauses the caller until a human decision is recorded on the pending action."""

    async def wait_for_decision(self, request: ApprovalRequest) -> None: ...


class ApprovalNotResolved(RuntimeError):
    """The run resumed while its pending action was still PENDING (a runner bug)."""


class ToolGate:
    def __init__(
        self,
        *,
        registry: ToolRegistry,
        scopes: AgentScopes,
        ledger: LedgerRepository,
        pending_actions: PendingActionRepository,
        approvals: ApprovalPort,
        policy: AutonomyPolicy,
        executor: ToolExecutor,
        events: EventEmitter,
        tracer: TracingClient,
        approval_ttl: timedelta,
    ) -> None:
        self._registry = registry
        self._scopes = scopes
        self._ledger = ledger
        self._pending = pending_actions
        self._approvals = approvals
        self._policy = policy
        self._executor = executor
        self._events = events
        self._tracer = tracer
        self._approval_ttl = approval_ttl

    async def call_tool(
        self,
        ctx: AgentContext,
        agent_name: str,
        tool: str,
        args: Mapping[str, Any] | None,
        *,
        call_id: str,
    ) -> ToolResult:
        raw_args = dict(args or {})
        async with self._tracer.span(
            f"tool:{tool}",
            kind="tool",
            inputs={"agent": agent_name, "args": raw_args},
            metadata={"session_id": str(ctx.session_id), "call_id": call_id},
        ) as span:
            result = await self._call(ctx, agent_name, tool, raw_args, call_id)
            span.set_outputs(result.for_model())
            return result

    # ------------------------------------------------------------------ checks
    async def _call(
        self, ctx: AgentContext, agent_name: str, tool: str, raw_args: dict[str, Any], call_id: str
    ) -> ToolResult:
        definition = self._registry.get(tool)
        if definition is None:
            return await self._refuse(ctx, agent_name, tool, raw_args, call_id, ToolOutcome.DENIED, f"unknown tool '{tool}'")

        if not self._scopes.allows(agent_name, definition):
            message = f"agent '{agent_name}' may not use '{tool}' (requires {definition.scope.value} scope)"
            return await self._refuse(ctx, agent_name, tool, raw_args, call_id, ToolOutcome.DENIED, message)

        smuggled = sorted(_IDENTITY_ARGS & raw_args.keys())
        if smuggled:
            message = f"identity is set by the platform, not tool arguments: {', '.join(smuggled)}"
            return await self._refuse(ctx, agent_name, tool, raw_args, call_id, ToolOutcome.DENIED, message)

        try:
            parsed = definition.input_model.model_validate(raw_args)
        except ValidationError as exc:
            message = f"invalid arguments: {describe_validation_error(exc)}"
            return await self._refuse(ctx, agent_name, tool, raw_args, call_id, ToolOutcome.INVALID, message)

        if definition.acl is not None:
            try:
                await definition.acl(ctx, parsed)
            except ToolAccessDenied as exc:
                message = str(exc) or f"access to '{tool}' denied"
                return await self._refuse(ctx, agent_name, tool, raw_args, call_id, ToolOutcome.DENIED, message)
            except Exception as exc:
                if is_control_flow_signal(exc):
                    raise
                logger.exception("access check for %s failed", tool)
                message = f"could not verify access for '{tool}': {type(exc).__name__}"
                return await self._refuse(ctx, agent_name, tool, raw_args, call_id, ToolOutcome.FAILED, message)

        if definition.kind is ToolKind.READ:
            await self._emit_call(ctx, agent_name, definition, parsed, call_id)
            return await self._execute_read(ctx, agent_name, definition, parsed, call_id)
        return await self._write(ctx, agent_name, definition, parsed, call_id)

    # ------------------------------------------------------------------ writes
    async def _write(
        self, ctx: AgentContext, agent_name: str, definition: ToolDefinition, parsed: ToolInput, call_id: str
    ) -> ToolResult:
        key = f"{ctx.session_id}:{call_id}"

        prior = await self._ledger.find_executed(tenant_id=ctx.tenant_id, idempotency_key=key)
        if prior is not None:
            step = await self._ledger.find_step(tenant_id=ctx.tenant_id, idempotency_key=key)
            return ToolResult(
                ok=True,
                tool=definition.name,
                call_id=call_id,
                outcome=ToolOutcome.EXECUTED,
                data=prior.result,
                summary=prior.result_summary,
                pending_action_id=prior.pending_action_id,
                duplicate=True,
                executed_args=prior.args,
                action_id=step.id if step is not None else None,
                undoable=step is not None and step.undo_action is not None,
            )

        pending = await self._pending.get_by_key(tenant_id=ctx.tenant_id, idempotency_key=key)
        reason = "writes need human approval"
        # An existing approval always takes the human path again, so the pause happens in
        # the same order on replay even if the policy's answer would differ now.
        if pending is None and ctx.mode is RunMode.AUTONOMOUS:
            try:
                decision = await self._policy.evaluate(ctx, definition, parsed)
            except Exception:
                # Never act alone on a policy we could not evaluate: fall through to a human.
                logger.exception("autonomy policy failed for %s; escalating", definition.name)
                decision = PolicyDecision(Verdict.ESCALATE, "autonomy policy could not be evaluated")
            if decision.verdict is Verdict.ALLOW:
                await self._emit_call(ctx, agent_name, definition, parsed, call_id)
                return await self._execute_write(ctx, agent_name, definition, parsed, call_id, key, None)
            reason = decision.reason

        if pending is None:
            try:
                preview = await definition.build_preview(ctx, parsed)
            except Exception as exc:
                if is_control_flow_signal(exc):
                    raise
                outcome, message = _classify_failure(exc, definition)
                if outcome is ToolOutcome.UNKNOWN or isinstance(exc, TimeoutError):
                    outcome = ToolOutcome.FAILED  # nothing has run yet
                message = f"could not prepare '{definition.name}' for approval: {message}"
                return await self._refuse(ctx, agent_name, definition.name, parsed.model_dump(mode="json"), call_id, outcome, message)
            pending, created = await self._pending.get_or_create(
                tenant_id=ctx.tenant_id,
                session_id=ctx.session_id,
                idempotency_key=key,
                agent=agent_name,
                tool=definition.name,
                args=parsed.model_dump(mode="json"),
                preview=to_jsonable_python(preview, fallback=str),
                expires_at=utcnow() + self._approval_ttl,
            )
            if created:
                await self._emit_call(ctx, agent_name, definition, parsed, call_id)
                await self._emit(
                    ctx.session_id,
                    EventType.AWAITING_APPROVAL,
                    {
                        "pending_action_id": pending.id,
                        "call_id": call_id,
                        "agent": agent_name,
                        "tool": definition.name,
                        "args": pending.args,
                        "preview": pending.preview,
                        "expires_at": pending.expires_at,
                        "reason": reason,
                    },
                )

        await self._approvals.wait_for_decision(
            ApprovalRequest(
                tenant_id=ctx.tenant_id,
                session_id=ctx.session_id,
                pending_action_id=pending.id,
                tool=definition.name,
                call_id=call_id,
            )
        )

        decided = await self._pending.get(tenant_id=ctx.tenant_id, action_id=pending.id)
        status = PendingActionStatus(decided.status) if decided else PendingActionStatus.PENDING
        if decided is None or status is PendingActionStatus.PENDING:
            raise ApprovalNotResolved(f"pending action {pending.id} resumed without a decision")

        if status is PendingActionStatus.REJECTED:
            message = "rejected by reviewer" + (f": {decided.decision_note}" if decided.decision_note else "")
            return await self._refuse(
                ctx, agent_name, definition.name, decided.args, call_id, ToolOutcome.REJECTED, message, decided.id
            )
        if status is PendingActionStatus.EXPIRED:
            message = "approval expired before a decision was made"
            return await self._refuse(
                ctx, agent_name, definition.name, decided.args, call_id, ToolOutcome.EXPIRED, message, decided.id
            )
        approved_args = (decided.edited_args or {}) if status is PendingActionStatus.EDITED else decided.args
        try:
            parsed = definition.input_model.model_validate(approved_args)
        except ValidationError as exc:
            what = "edited arguments" if status is PendingActionStatus.EDITED else "approved arguments"
            message = f"{what} are invalid: {describe_validation_error(exc)}"
            return await self._refuse(
                ctx, agent_name, definition.name, approved_args, call_id, ToolOutcome.INVALID, message, decided.id
            )
        return await self._execute_write(ctx, agent_name, definition, parsed, call_id, key, decided.id)

    async def _execute_write(
        self,
        ctx: AgentContext,
        agent_name: str,
        definition: ToolDefinition,
        parsed: ToolInput,
        call_id: str,
        key: str,
        pending_action_id: UUID | None,
    ) -> ToolResult:
        args_json = parsed.model_dump(mode="json")
        step, created = await self._ledger.begin_step(
            tenant_id=ctx.tenant_id,
            session_id=ctx.session_id,
            action=definition.name,
            idempotency_key=key,
            turn=ctx.turn,
        )
        if not created:
            if step.status == SagaStatus.PENDING:
                outcome = ToolOutcome.UNKNOWN
                message = (
                    f"a previous attempt at '{definition.name}' stopped before confirming, so it MAY HAVE HAPPENED. "
                    "Do not retry it; ask the user to check."
                )
            else:
                outcome = ToolOutcome.FAILED
                message = step.error or f"'{definition.name}' already failed"
            return await self._refuse(
                ctx, agent_name, definition.name, args_json, call_id, outcome, message, pending_action_id
            )

        started = time.monotonic()
        try:
            output = await self._executor.run(
                definition, ToolInvocation(ctx, agent_name, call_id, parsed, pending_action_id=pending_action_id)
            )
        except Exception as exc:
            if is_control_flow_signal(exc):
                raise
            outcome, message = _classify_failure(exc, definition)
            audit = AuditFields(
                tenant_id=ctx.tenant_id,
                session_id=ctx.session_id,
                user_id=ctx.user_id,
                agent=agent_name,
                tool=definition.name,
                args=args_json,
                outcome=outcome,
                result_summary=message,
                idempotency_key=key,
                pending_action_id=pending_action_id,
                duration_ms=_elapsed_ms(started),
            )
            if outcome is ToolOutcome.UNKNOWN:
                # The side effect may have happened: the saga step stays PENDING, so a replay
                # of this call is refused instead of acting twice.
                await self._ledger.record(audit)
            else:
                await self._ledger.fail_write(audit, step_id=step.id, error=message)
            await self._emit_result(ctx, call_id, agent_name, definition.name, outcome, error=message)
            return ToolResult(
                ok=False, tool=definition.name, call_id=call_id, outcome=outcome, error=message,
                pending_action_id=pending_action_id, executed_args=args_json,
            )

        data = to_jsonable_python(output.data, fallback=str)
        undo_action = None
        if output.undo is not None:
            if definition.undo_handler is None:
                logger.warning("tool %s returned an undo plan but has no undo handler; ignoring it", definition.name)
            else:
                undo_action = {
                    "tool": definition.name,
                    "args": to_jsonable_python(output.undo.args, fallback=str),
                    "label": output.undo.label,
                }
        await self._ledger.complete_write(
            AuditFields(
                tenant_id=ctx.tenant_id,
                session_id=ctx.session_id,
                user_id=ctx.user_id,
                agent=agent_name,
                tool=definition.name,
                args=args_json,
                outcome=ToolOutcome.EXECUTED,
                result_summary=output.summary,
                result=data,
                idempotency_key=key,
                pending_action_id=pending_action_id,
                duration_ms=_elapsed_ms(started),
            ),
            step_id=step.id,
            ref_id=output.ref_id,
            undo_action=undo_action,
        )
        await self._emit_result(
            ctx, call_id, agent_name, definition.name, ToolOutcome.EXECUTED, summary=output.summary,
            sources=output.sources,
        )
        return ToolResult(
            ok=True, tool=definition.name, call_id=call_id, outcome=ToolOutcome.EXECUTED, data=data,
            summary=output.summary, pending_action_id=pending_action_id, executed_args=args_json,
            sources=output.sources, action_id=step.id, undoable=undo_action is not None,
        )

    # ------------------------------------------------------------------ reads
    async def _execute_read(
        self, ctx: AgentContext, agent_name: str, definition: ToolDefinition, parsed: ToolInput, call_id: str
    ) -> ToolResult:
        args_json = parsed.model_dump(mode="json")
        started = time.monotonic()
        try:
            output = await self._executor.run(definition, ToolInvocation(ctx, agent_name, call_id, parsed))
        except Exception as exc:
            if is_control_flow_signal(exc):
                raise
            outcome, message = _classify_failure(exc, definition)
            await self._audit(ctx, agent_name, definition.name, args_json, outcome, message, duration_ms=_elapsed_ms(started))
            await self._emit_result(ctx, call_id, agent_name, definition.name, outcome, error=message)
            return ToolResult(ok=False, tool=definition.name, call_id=call_id, outcome=outcome, error=message)

        await self._audit(
            ctx, agent_name, definition.name, args_json, ToolOutcome.EXECUTED, output.summary,
            duration_ms=_elapsed_ms(started),
        )
        await self._emit_result(
            ctx, call_id, agent_name, definition.name, ToolOutcome.EXECUTED, summary=output.summary,
            sources=output.sources,
        )
        return ToolResult(
            ok=True, tool=definition.name, call_id=call_id, outcome=ToolOutcome.EXECUTED,
            data=to_jsonable_python(output.data, fallback=str), summary=output.summary, sources=output.sources,
        )

    # ------------------------------------------------------------------ helpers
    async def _refuse(
        self,
        ctx: AgentContext,
        agent_name: str,
        tool: str,
        args: Mapping[str, Any],
        call_id: str,
        outcome: ToolOutcome,
        message: str,
        pending_action_id: UUID | None = None,
    ) -> ToolResult:
        if outcome is ToolOutcome.DENIED:
            logger.warning("tool call denied session=%s agent=%s tool=%s: %s", ctx.session_id, agent_name, tool, message)
        await self._audit(ctx, agent_name, tool, args, outcome, message, pending_action_id=pending_action_id)
        await self._emit_result(ctx, call_id, agent_name, tool, outcome, error=message)
        return ToolResult(
            ok=False, tool=tool, call_id=call_id, outcome=outcome, error=message, pending_action_id=pending_action_id
        )

    async def _audit(
        self,
        ctx: AgentContext,
        agent_name: str,
        tool: str,
        args: Mapping[str, Any],
        outcome: ToolOutcome,
        summary: str | None,
        *,
        pending_action_id: UUID | None = None,
        duration_ms: int | None = None,
    ) -> None:
        await self._ledger.record(
            AuditFields(
                tenant_id=ctx.tenant_id,
                session_id=ctx.session_id,
                user_id=ctx.user_id,
                agent=agent_name,
                tool=tool,
                args=to_jsonable_python(dict(args), fallback=str),
                outcome=outcome,
                result_summary=summary,
                pending_action_id=pending_action_id,
                duration_ms=duration_ms,
            )
        )

    async def _emit_call(
        self, ctx: AgentContext, agent_name: str, definition: ToolDefinition, parsed: ToolInput, call_id: str
    ) -> None:
        await self._emit(
            ctx.session_id,
            EventType.TOOL_CALL,
            {
                "call_id": call_id,
                "agent": agent_name,
                "tool": definition.name,
                "kind": definition.kind.value,
                "args": parsed.model_dump(mode="json"),
            },
        )

    async def _emit_result(
        self,
        ctx: AgentContext,
        call_id: str,
        agent_name: str,
        tool: str,
        outcome: ToolOutcome,
        *,
        summary: str | None = None,
        error: str | None = None,
        sources: Sequence[SourceLink] = (),
    ) -> None:
        data: dict[str, Any] = {
            "call_id": call_id,
            "agent": agent_name,
            "tool": tool,
            "ok": outcome is ToolOutcome.EXECUTED,
            "outcome": outcome.value,
            "summary": summary,
            "error": error,
        }
        if sources:
            data["sources"] = [source.to_dict() for source in sources]
        await self._emit(ctx.session_id, EventType.TOOL_RESULT, data)

    async def _emit(self, session_id: UUID, type: EventType, data: Mapping[str, Any]) -> None:
        await emit_best_effort(self._events, session_id, type, data)


def _classify_failure(exc: Exception, definition: ToolDefinition) -> tuple[ToolOutcome, str]:
    if isinstance(exc, ToolAccessDenied):
        return ToolOutcome.DENIED, str(exc) or f"access to '{definition.name}' denied"
    if isinstance(exc, ToolInputError):
        return ToolOutcome.INVALID, str(exc) or f"invalid input for '{definition.name}'"
    unknown = isinstance(exc, ToolOutcomeUnknown) or (isinstance(exc, TimeoutError) and definition.kind is ToolKind.WRITE)
    if unknown:
        # A timed-out write keeps running in the connector: it is not a failure we can report as one.
        return ToolOutcome.UNKNOWN, (
            f"'{definition.name}' did not confirm whether it completed, so it MAY HAVE HAPPENED. "
            "Do not retry it; ask the user to check (for email, their Sent folder)."
        )
    if isinstance(exc, TimeoutError):
        return ToolOutcome.FAILED, f"'{definition.name}' timed out"
    if isinstance(exc, ToolFailed):
        logger.warning("tool %s failed: %s", definition.name, exc)
        return ToolOutcome.FAILED, str(exc) or f"'{definition.name}' failed"
    logger.exception("tool %s raised", definition.name)
    return ToolOutcome.FAILED, f"'{definition.name}' failed: {type(exc).__name__}: {str(exc)[:300]}"


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
