"""The orchestrator: sole coordinator of a session (implementation-plan §0.4, §10 Phases 1–3).

    plan ──(tool calls?)──► act ──(more calls?)──► act ─ … ─► plan ─ … ─► END
                             │
                             └─(a write failed after others succeeded)──► compensate ──► plan

- ``plan`` asks the model router for the next step and streams its tokens to the session.
- ``act`` runs pending tool calls through the Tool Gate: ONE write per super-step, so a
  run that pauses for approval resumes by re-running only that call (the gate turns the
  re-run into a lookup, see ``langgraph_runtime``). Consecutive reads can't pause and have
  no side effects, so they run together in one step. When a write doesn't go through, the
  rest of that step's calls are skipped so the model re-plans with what actually happened.
- ``compensate`` runs when a write FAILED, gave no answer, or its approval expired while
  earlier actions of the same request had completed: it proposes ``undo_actions`` for those
  actions, which pauses for the rep like any write (nothing is undone without their OK).
- ``delegate`` hands a piece of work to a sub-agent (research / outreach / quote). The sub-agent's
  own short conversation lives in ``delegations`` in this state, so a write inside it pauses and
  resumes like any other; only its result goes back to the planner. Its tools come from its scope
  and are enforced at the gate, and read-only sub-agents can run side by side.
- Guardrails: per-turn limits on model steps, tool calls and tokens, and loop detection,
  checked before each model call and before running what the model asked for. A breach
  ends the turn HALTED with an explanation instead of spinning.
"""

from __future__ import annotations

import asyncio
import json
import logging
import operator
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, TypedDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.clock import utcnow
from app.core.context import AgentContext
from app.core.enums import ToolOutcome
from app.context.manager import ContextManager
from app.engine.delegation import DELEGATE_TOOL, SUBAGENTS, note_call, reply_message, result_content
from app.engine.delegation import start as start_delegation
from app.engine.events import EventEmitter, EventType, emit_best_effort
from app.engine.guardrails.budgets import TenantBudgets
from app.engine.guardrails.limits import Halt, TurnLimits, check_before_step, check_calls
from app.engine.guardrails.saga import UNDO_TOOL, Compensator
from app.engine.workspace_record import WorkspaceRecorder, describe_action
from app.models.router import ModelRouter
from app.models.types import (
    Completion,
    Complexity,
    Message,
    ProviderError,
    Role,
    StreamDone,
    StreamRestart,
    TaskSpec,
    TextDelta,
    ToolCall,
    ToolSpec,
)
from app.platform.langgraph_runtime import END, GraphSpec, current_context, is_control_flow_signal
from app.tools.gate import ToolGate
from app.tools.registry import AgentScopes, ToolRegistry
from app.tools.types import ToolKind, ToolResult

logger = logging.getLogger(__name__)

AGENT_NAME = "orchestrator"

SYSTEM_PROMPT = """You are RoleSync's sales assistant. You work for one sales rep inside their workspace.

How to work:
- Use the tools to take action. Never say an action happened unless its tool result has outcome EXECUTED.
- Actions that change anything outside this chat (email, calendar invites, Slack messages, Notion pages, documents,
  quotes, catalog and stock changes) automatically pause for the rep's approval. Call the tool directly with
  complete, final content; do not ask for permission in chat first. Run such actions one at a time.
- If an action is REJECTED, do not retry it unchanged: ask what the rep wants changed.
  If it FAILED or was DENIED, say so briefly and suggest a next step (for example, connecting an app).
- If an action's outcome is UNKNOWN it may already have happened: never retry it. Tell the rep and ask
  them to check (for email, their Sent folder).
- When an action fails after others in the same request succeeded, the rep is automatically asked whether to
  undo the completed ones; the undo_actions result shows what they decided. After that, stop: report what
  failed and what was undone or kept, and let the rep decide what happens next.
- Every completed action's result has an action_id. If the rep asks to take something back, call undo_actions
  with those ids. Sent emails can't be undone.

Research and answers:
- Reading never needs approval. Before answering questions about prospects, customers, products or the rep's
  own history, gather facts with the read tools, and use every source the question spans (web, emails,
  calendar, Slack, Notion, knowledge base, catalog). Request independent reads together in one step.
- Base answers only on tool results. Cite web facts with their URLs and name the documents, emails or messages
  you used. If something wasn't found, say so instead of guessing.
- When a source finds nothing, try at most one differently worded search there, then report it as not found.
  Don't retry sources that were DENIED (for example, an app that isn't connected).
- Prices, discounts and stock come only from the catalog tools. Quotes are priced by create_quote from the
  catalog, within each item's discount limit.
- Documents and quotes are saved to the rep's Google Drive, or to the workspace knowledge base when Drive isn't
  available. Share the link from the result.

Deals and memory:
- Deals are shared by the workspace. Use search_deals before create_deal so you don't create duplicates, keep a
  deal's stage and next step current with update_deal (for example PROPOSAL once a quote is sent, WON or LOST when
  it closes), and pass deal_id to create_quote to attach the quote to its deal.
- You remember things between conversations. Before working on a customer, recall what is known about the company
  (and its deal). As you learn durable facts, save them with remember without asking: the rep's preferences
  (about=rep), and facts about a customer company such as contacts and their roles, needs, objections, budget,
  timeline, competitors and what was quoted (about=account), or about one deal (about=deal). Account and deal
  memories are shared with the workspace. Don't save secrets (passwords, payment details), one-off chatter, or what
  the catalog and knowledge base already hold. If the rep says a remembered fact is wrong, forget it.
- A tool result that was too long to keep shows "offloaded": call read_offloaded_result with its ref when you need
  the details.

Sub-agents:
- You are the only one who talks to the rep. When a part of the request takes several steps in one area, hand that
  part to a sub-agent with delegate and work from its result: research (gathering facts anywhere and writing a cited
  brief), outreach (writing and sending email, calendar invites, Slack messages, Notion pages) and quote (pricing
  from the catalog and producing the quote document). Do single, simple steps yourself.
- A sub-agent cannot see this conversation: put everything it needs in task, and the facts it should work from in
  context. You get its result, not its steps, so pass on what the rep needs to see. Its actions still pause for the
  rep's approval, and the approval card names it.

Write in clear, professional, friendly language. Keep chat replies short unless the rep asks for detail.

{time_context}"""

WRAP_UP_NOTE = """This request stopped because an action didn't go through, and the rep has decided whether to undo
the actions it had completed (see the undo_actions result). Take no further action in this request: briefly tell
the rep what failed and what was undone or kept, then ask how they'd like to continue."""

_TOKEN_FLUSH_CHARS = 64
_TOKEN_FLUSH_SECONDS = 0.1
_COMPENSATE_ON = frozenset({ToolOutcome.FAILED, ToolOutcome.UNKNOWN, ToolOutcome.EXPIRED})


@dataclass(frozen=True, slots=True)
class _SubStep:
    """What one sub-agent thought this step: what it wants to run, or its finished answer."""

    delegation: dict[str, Any]
    calls: list[dict[str, Any]]
    answer: str | None
    tokens: int


class OrchestratorState(TypedDict, total=False):
    messages: Annotated[list[dict[str, Any]], operator.add]
    pending_calls: list[dict[str, Any]]
    steps: int  # model calls this turn
    tokens: int  # model tokens this turn
    tool_calls: int  # tool calls requested this turn
    call_counts: dict[str, int]  # identical-call fingerprints this turn (loop detection)
    time_zone: str | None  # the rep's IANA time zone, from their browser
    final_answer: str | None
    halt: dict[str, str] | None  # set when a guardrail stopped the turn
    rollback: dict[str, Any] | None  # completed actions to offer undoing, set by `act`
    wrap_up: bool  # after an undo decision: the model may only report back, not act again this turn
    delegations: list[dict[str, Any]]  # sub-agents running right now, each with its own conversation
    replan: bool  # a sub-agent just finished: the planner decides what to do with its result


def turn_input(user_message: str, *, time_zone: str | None = None) -> dict[str, Any]:
    """Graph input for a new user turn (also resets per-turn bookkeeping)."""
    update: dict[str, Any] = {
        "messages": [Message(role=Role.USER, content=user_message).to_dict()],
        "pending_calls": [],
        "steps": 0,
        "tokens": 0,
        "tool_calls": 0,
        "call_counts": {},
        "final_answer": None,
        "halt": None,
        "rollback": None,
        "wrap_up": False,
        "delegations": [],
        "replan": False,
    }
    if time_zone:
        update["time_zone"] = time_zone
    return update


class Orchestrator:
    def __init__(
        self,
        *,
        router: ModelRouter,
        gate: ToolGate,
        registry: ToolRegistry,
        scopes: AgentScopes,
        events: EventEmitter,
        recorder: WorkspaceRecorder,
        limits: TurnLimits,
        compensator: Compensator | None = None,
        budgets: TenantBudgets | None = None,
        context: ContextManager | None = None,
    ) -> None:
        self._router = router
        self._gate = gate
        self._registry = registry
        self._scopes = scopes
        self._events = events
        self._recorder = recorder
        self._limits = limits
        self._compensator = compensator
        self._budgets = budgets
        self._context = context

    def graph_spec(self) -> GraphSpec:
        return GraphSpec(
            state_schema=OrchestratorState,
            nodes={"plan": self.plan, "act": self.act, "compensate": self.compensate},
            entry="plan",
            edges=[("compensate", "plan")],
            routers=[
                ("plan", _after_plan, {"act": "act", "plan": "plan", "end": END}),
                ("act", _after_act, {"act": "act", "plan": "plan", "compensate": "compensate"}),
            ],
        )

    async def plan(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("delegations"):
            return await self._plan_delegations(state)
        ctx = current_context()
        steps_taken = int(state.get("steps") or 0)
        tokens = int(state.get("tokens") or 0)
        history = state.get("messages") or []

        halt = check_before_step(self._limits, steps_taken=steps_taken, tokens_used=tokens)
        if halt is not None:
            return _halted(halt, steps=steps_taken)

        steps = steps_taken + 1
        wrap_up = bool(state.get("wrap_up"))
        await emit_best_effort(self._events, ctx.session_id, EventType.STEP_STARTED, {"step": "planning", "number": steps})
        system = SYSTEM_PROMPT.format(time_context=_time_context(state.get("time_zone")))
        if wrap_up:
            system = f"{system}\n\n{WRAP_UP_NOTE}"
        tools = self._tool_specs()
        if self._context is not None:

            async def announce_fold() -> None:
                await emit_best_effort(
                    self._events, ctx.session_id, EventType.STEP_STARTED, {"step": "summarizing earlier conversation"}
                )

            prepared = await self._context.prepare(ctx, history=history, system=system, tools=tools, on_fold=announce_fold)
            system, visible = prepared.system, list(prepared.messages)
        else:
            visible = [Message.from_dict(item) for item in history]
        task = TaskSpec(
            purpose="plan",
            system=system,
            messages=repair_history(visible),
            tools=tools,
            complexity=Complexity.HIGH,
            allow_tool_calls=not wrap_up,
        )
        completion = await self._stream(ctx.session_id, task)
        used = completion.usage.input_tokens + completion.usage.output_tokens
        if self._budgets is not None:
            await self._budgets.record_tokens(ctx.tenant_id, used)
        message = completion.message
        if wrap_up and message.tool_calls:
            # A model that ignores the "no calls" instruction still can't act again in this request.
            logger.info("dropping %d tool call(s) after an undo decision in session %s", len(message.tool_calls), ctx.session_id)
            message = Message(role=Role.ASSISTANT, content=message.content.strip() or _wrap_up_text(history))
        # The gate's idempotency key must be unique per session even if a model reuses its
        # own call ids across turns, so prefix it with the history position (stable on replay).
        position = len(history)
        calls = [
            {**call.to_dict(), "gate_call_id": f"{position}-{index}-{call.id}", "agent": AGENT_NAME}
            for index, call in enumerate(message.tool_calls)
        ]
        update: dict[str, Any] = {
            "messages": [message.to_dict()],
            "pending_calls": calls,
            "steps": steps,
            "tokens": tokens + used,
            "final_answer": None if calls else message.content,
            "replan": False,
        }
        if not calls:
            return update

        halt, counts = check_calls(
            self._limits,
            calls_made=int(state.get("tool_calls") or 0),
            seen=state.get("call_counts") or {},
            calls=[(call["name"], call.get("arguments")) for call in calls],
        )
        update |= {"tool_calls": int(state.get("tool_calls") or 0) + len(calls), "call_counts": counts}
        if halt is not None:
            # Answer every requested call so the history stays well-formed for the next turn.
            skipped = [_skipped_reply(call, "not run: the request was stopped by a safety limit").to_dict() for call in calls]
            stopped = _halted(halt, steps=steps)
            return update | stopped | {"messages": [message.to_dict(), *skipped, *stopped["messages"]]}
        return update

    async def act(self, state: dict[str, Any]) -> dict[str, Any]:
        ctx = current_context()
        pending = state["pending_calls"]
        batch = self._next_batch(pending)
        outcomes = await asyncio.gather(*(self._run_call(ctx, call) for call in batch))
        running = {str(item["id"]): dict(item) for item in state.get("delegations") or []}
        started: list[dict[str, Any]] = []
        messages: list[dict[str, Any]] = []

        def deliver(call: dict[str, Any], reply: Message, result: ToolResult | None = None) -> None:
            """A reply goes to whoever made the call: a sub-agent's own conversation, or the planner's."""
            owner = running.get(str(call.get("delegation") or ""))
            if owner is None:
                messages.append(reply.to_dict())
                return
            owner["messages"] = [*owner["messages"], reply.to_dict()]
            if result is not None:
                note_call(owner, call["name"], result.outcome.value, result.summary, [s.to_dict() for s in result.sources])

        for call, (reply, result) in zip(batch, outcomes, strict=True):
            if call["name"] == DELEGATE_TOOL and result.outcome is ToolOutcome.EXECUTED:
                # Its reply is the sub-agent's result, once there is one.
                started.append(start_delegation(call, result.executed_args or call.get("arguments") or {}))
                continue
            deliver(call, reply, result)

        update: dict[str, Any] = {"messages": messages, "pending_calls": pending[len(batch) :]}

        failed = next(
            (
                (call, result)
                for call, (_, result) in zip(batch, outcomes, strict=True)
                if self._is_write(call["name"]) and result.outcome is not ToolOutcome.EXECUTED
            ),
            None,
        )
        if failed is None:
            update["delegations"] = [*running.values(), *started]
            return update

        call, result = failed
        remaining = pending[len(batch) :]
        if remaining:
            reason = f"not run: '{call['name']}' did not go through ({result.outcome.value}), so the plan needs another look"
            for item in remaining:
                deliver(item, _skipped_reply(item, reason))
            update["pending_calls"] = []
        update["delegations"] = [*running.values(), *started]
        if result.outcome in _COMPENSATE_ON and call["name"] != UNDO_TOOL and self._compensator is not None:
            completed = await self._compensator.undoable_in_turn(ctx)
            if completed:
                detail = result.error or result.outcome.value.lower()
                action, _ = describe_action(call["name"], result.executed_args or call.get("arguments"))
                update["rollback"] = {
                    "action_ids": [str(step.id) for step in completed],
                    "reason": f"{action} didn't go through: {detail}"[:500],
                }
        return update

    async def compensate(self, state: dict[str, Any]) -> dict[str, Any]:
        """Offer to undo the request's completed actions. The arguments come from checkpointed
        state, so a run resumed after the rep's decision executes exactly what they approved."""
        ctx = current_context()
        rollback = state.get("rollback") or {}
        history = state.get("messages") or []
        position = len(history)
        arguments = {"action_ids": list(rollback.get("action_ids") or []), "reason": str(rollback.get("reason") or "")}
        model_call_id = f"undo_{position}"
        await emit_best_effort(self._events, ctx.session_id, EventType.STEP_STARTED, {"step": "offering to undo"})
        call = {"id": model_call_id, "name": UNDO_TOOL, "arguments": arguments, "gate_call_id": f"{position}-0-undo", "agent": AGENT_NAME}
        reply, _ = await self._run_call(ctx, call)
        proposal = Message(role=Role.ASSISTANT, content="", tool_calls=(ToolCall(id=model_call_id, name=UNDO_TOOL, arguments=arguments),))
        stopped = "stopped: an action in this request didn't go through"
        closing = [reply_message(item, result_content(item, "", stopped=stopped)).to_dict() for item in state.get("delegations") or []]
        # Whatever the rep decided, this request is over: the model reports back and they choose what's next.
        return {
            "messages": [*closing, proposal.to_dict(), reply.to_dict()],
            "rollback": None,
            "wrap_up": True,
            "delegations": [],
        }

    def _next_batch(self, pending: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The next call alone, or, if it is a read, it and the reads directly after it."""
        batch: list[dict[str, Any]] = []
        for call in pending:
            is_read = not self._is_write(call["name"])
            if batch and not is_read:
                break
            batch.append(call)
            if not is_read:
                break
        return batch

    def _is_write(self, name: str) -> bool:
        definition = self._registry.get(name)
        return definition is not None and definition.kind is ToolKind.WRITE

    async def _run_call(self, ctx: AgentContext, call: dict[str, Any]) -> tuple[Message, ToolResult]:
        arguments = call.get("arguments") or {}
        agent = str(call.get("agent") or AGENT_NAME)
        try:
            result = await self._gate.call_tool(ctx, agent, call["name"], arguments, call_id=call["gate_call_id"])
        except Exception as exc:
            if is_control_flow_signal(exc):
                raise  # an approval pause
            # Keep the conversation well-formed (every call gets a reply) instead of failing the run.
            logger.exception("tool call %s crashed in session %s", call.get("name"), ctx.session_id)
            result = ToolResult(
                ok=False,
                tool=str(call.get("name")),
                call_id=call["gate_call_id"],
                outcome=ToolOutcome.FAILED,
                error=f"internal error while running '{call.get('name')}'; it may not have completed",
            )

        if self._is_write(call["name"]):
            await self._recorder.action_finished(
                ctx,
                idempotency_key=f"{ctx.session_id}:{call['gate_call_id']}",
                agent=agent,
                tool=call["name"],
                args=result.executed_args or arguments,  # a reviewer may have edited them
                result=result,
            )
        content = json.dumps(result.for_model())
        if self._context is not None:
            content = await self._context.keep_result(ctx, call_id=call["gate_call_id"], tool=call["name"], content=content)
        reply = Message(role=Role.TOOL, content=content, tool_call_id=call["id"], name=call["name"])
        return reply, result

    def _tool_specs(self, agent_name: str = AGENT_NAME) -> tuple[ToolSpec, ...]:
        return tuple(
            ToolSpec(name=d.name, description=d.description, parameters=_clean_schema(d.parameters_schema()))
            for d in self._scopes.tools_for(agent_name, self._registry)
        )

    # ------------------------------------------------------------------ sub-agents
    async def _plan_delegations(self, state: dict[str, Any]) -> dict[str, Any]:
        """One model step for each running sub-agent. They are independent, so they think together;
        what they then ask for is run by ``act`` under their own name."""
        ctx = current_context()
        running = [dict(item) for item in state.get("delegations") or []]
        steps_taken = int(state.get("steps") or 0)
        tokens = int(state.get("tokens") or 0)

        halt = check_before_step(self._limits, steps_taken=steps_taken, tokens_used=tokens)
        if halt is not None:
            return self._stop_delegations(running, _halted(halt, steps=steps_taken), halt.message)

        steps = steps_taken + 1
        working = ", ".join(SUBAGENTS[item["agent"]].title for item in running)
        await emit_best_effort(self._events, ctx.session_id, EventType.STEP_STARTED, {"step": f"{working} working", "number": steps})
        outcomes = await asyncio.gather(*(self._subagent_step(ctx, item, state) for item in running))

        used = sum(outcome.tokens for outcome in outcomes)
        if self._budgets is not None and used:
            await self._budgets.record_tokens(ctx.tenant_id, used)

        calls: list[dict[str, Any]] = []
        still: list[dict[str, Any]] = []
        replies: list[dict[str, Any]] = []
        for outcome in outcomes:
            if outcome.calls:
                calls += outcome.calls
                still.append(outcome.delegation)
                continue
            replies.append((await self._finish_delegation(ctx, outcome.delegation, outcome.answer or "")).to_dict())

        update: dict[str, Any] = {
            "messages": replies,
            "delegations": still,
            "pending_calls": calls,
            "steps": steps,
            "tokens": tokens + used,
            # A finished sub-agent hands its result back to the planner, which decides what happens next.
            "replan": bool(replies),
        }
        if not calls:
            return update

        halt, counts = check_calls(
            self._limits,
            calls_made=int(state.get("tool_calls") or 0),
            seen=state.get("call_counts") or {},
            calls=[(call["name"], call.get("arguments")) for call in calls],
        )
        update |= {"tool_calls": int(state.get("tool_calls") or 0) + len(calls), "call_counts": counts}
        if halt is not None:
            stopped = self._stop_delegations(still, _halted(halt, steps=steps), halt.message)
            return update | stopped | {"messages": [*replies, *stopped["messages"]]}
        return update

    async def _subagent_step(self, ctx: AgentContext, delegation: dict[str, Any], state: dict[str, Any]) -> _SubStep:
        agent = SUBAGENTS[delegation["agent"]]
        history = [Message.from_dict(item) for item in delegation.get("messages") or []]
        steps = int(delegation.get("steps") or 0) + 1
        last = steps >= agent.max_steps
        system = f"{agent.prompt}\n\n{_time_context(state.get('time_zone'))}"
        if self._context is not None:
            rep = await self._context.rep_context(ctx)
            if rep:
                system = f"{system}\n\n{rep}"
        if last:
            system = f"{system}\n\nThis is your last step: answer now with what you have."
        task = TaskSpec(
            purpose=f"subagent:{agent.name}",
            system=system,
            messages=repair_history(history),
            tools=self._tool_specs(agent.name),
            complexity=Complexity.HIGH,
            allow_tool_calls=not last,
        )
        completion = await self._router.complete(task)
        message = completion.message
        if last and message.tool_calls:
            message = Message(role=Role.ASSISTANT, content=message.content.strip() or "I ran out of steps before finishing this.")
        messages = [*(delegation.get("messages") or []), message.to_dict()]
        updated = {**delegation, "messages": messages, "steps": steps}
        calls = [
            {
                **call.to_dict(),
                "gate_call_id": f"{delegation['id']}|{len(messages)}-{index}-{call.id}",
                "agent": agent.name,
                "delegation": delegation["id"],
            }
            for index, call in enumerate(message.tool_calls)
        ]
        used = completion.usage.input_tokens + completion.usage.output_tokens
        return _SubStep(delegation=updated, calls=calls, answer=None if calls else message.content, tokens=used)

    async def _finish_delegation(self, ctx: AgentContext, delegation: dict[str, Any], answer: str, stopped: str | None = None) -> Message:
        content = result_content(delegation, answer, stopped=stopped)
        if self._context is not None:
            content = await self._context.keep_result(ctx, call_id=delegation["id"], tool=DELEGATE_TOOL, content=content)
        agent = SUBAGENTS[delegation["agent"]]
        await emit_best_effort(
            self._events,
            ctx.session_id,
            EventType.TOOL_RESULT,
            {
                "call_id": delegation["id"],
                "agent": agent.name,
                "tool": DELEGATE_TOOL,
                "outcome": "EXECUTED" if stopped is None else "FAILED",
                "summary": f"{agent.title}: {(answer or stopped or '').strip()[:400]}",
                "sources": delegation.get("sources") or [],
            },
        )
        return reply_message(delegation, content)

    def _stop_delegations(self, running: list[dict[str, Any]], stopped: dict[str, Any], reason: str) -> dict[str, Any]:
        """End every running sub-agent because the turn is over, answering each delegate call."""
        closing = [reply_message(item, result_content(item, "", stopped=reason)).to_dict() for item in running]
        return stopped | {"messages": [*closing, *stopped["messages"]], "delegations": [], "pending_calls": []}

    async def _stream(self, session_id, task: TaskSpec) -> Completion:
        buffer: list[str] = []
        last_flush = time.monotonic()

        async def flush() -> None:
            nonlocal last_flush
            if buffer:
                await emit_best_effort(self._events, session_id, EventType.TOKEN, {"text": "".join(buffer)})
                buffer.clear()
            last_flush = time.monotonic()

        async for event in self._router.stream(task):
            if isinstance(event, TextDelta):
                buffer.append(event.text)
                if sum(map(len, buffer)) >= _TOKEN_FLUSH_CHARS or time.monotonic() - last_flush >= _TOKEN_FLUSH_SECONDS:
                    await flush()
            elif isinstance(event, StreamRestart):
                buffer.clear()
                await emit_best_effort(self._events, session_id, EventType.TOKEN, {"reset": True, "reason": event.reason})
            elif isinstance(event, StreamDone):
                await flush()
                return event.completion
        raise ProviderError("model stream ended without a completion")


def repair_history(messages: list[Message]) -> tuple[Message, ...]:
    """Give every tool call a reply before the history reaches a model.

    A run that crashed mid-step leaves an assistant message whose calls were never answered;
    providers reject such a history (OpenAI-compatible APIs with a 400). The missing replies
    are filled in with an explicit "did not complete" result; the stored state is unchanged.
    """
    repaired: list[Message] = []
    open_calls: dict[str, str] = {}

    def close_open_calls() -> None:
        for call_id, name in open_calls.items():
            repaired.append(
                Message(
                    role=Role.TOOL,
                    content=json.dumps(
                        {"ok": False, "outcome": "FAILED", "error": "this action did not complete (the run was interrupted)"}
                    ),
                    tool_call_id=call_id,
                    name=name,
                )
            )
        open_calls.clear()

    for message in messages:
        if message.role is Role.TOOL:
            open_calls.pop(message.tool_call_id or "", None)
            repaired.append(message)
            continue
        close_open_calls()
        repaired.append(message)
        if message.role is Role.ASSISTANT:
            open_calls.update({call.id: call.name for call in message.tool_calls})
    # Calls at the very end are still pending (the next step executes them); leave them open.
    return tuple(repaired)


def valid_time_zone(name: str | None) -> str | None:
    """The IANA zone name if it is one this process knows, else ``None``."""
    if not name:
        return None
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return name


def _time_context(time_zone: str | None) -> str:
    now = utcnow()
    zone = valid_time_zone(time_zone)
    if zone is None:
        return f"Today is {now.date().isoformat()} (UTC). The rep's time zone is unknown: ask before scheduling at a clock time."
    local: datetime = now.astimezone(ZoneInfo(zone))
    return (
        f"It is {local.strftime('%A %Y-%m-%d %H:%M')} in the rep's time zone ({zone}). "
        "Use that zone for dates and meeting times unless the rep says otherwise."
    )


def _wrap_up_text(history: list[dict[str, Any]]) -> str:
    """A plain report of the undo decision, for a model that answered with calls instead of words."""
    for item in reversed(history):
        if item.get("role") == "tool" and item.get("name") == UNDO_TOOL:
            try:
                result = json.loads(item.get("content") or "{}")
            except json.JSONDecodeError:
                result = {}
            detail = result.get("summary") or result.get("error") or str(result.get("outcome", "")).lower()
            return f"An action didn't go through, so I stopped this request. Undo: {detail}. How would you like to continue?"
    return "An action didn't go through, so I stopped this request. How would you like to continue?"


def _halted(halt: Halt, *, steps: int) -> dict[str, Any]:
    return {
        "messages": [Message(role=Role.ASSISTANT, content=halt.message).to_dict()],
        "pending_calls": [],
        "steps": steps,
        "final_answer": halt.message,
        "halt": halt.to_dict(),
    }


def _skipped_reply(call: dict[str, Any], reason: str) -> Message:
    return Message(
        role=Role.TOOL,
        content=json.dumps({"ok": False, "outcome": "FAILED", "error": reason}),
        tool_call_id=call["id"],
        name=call["name"],
    )


def _after_plan(state: dict[str, Any]) -> str:
    if state.get("halt"):
        return "end"
    if state.get("pending_calls"):
        return "act"
    return "plan" if state.get("replan") else "end"


def _after_act(state: dict[str, Any]) -> str:
    if state.get("rollback"):
        return "compensate"
    return "act" if state.get("pending_calls") else "plan"


def _clean_schema(schema: Any) -> Any:
    """Drop Pydantic's cosmetic ``title`` annotations and inline its ``$defs`` references:
    models only need the structure, and not every provider resolves ``$ref``.
    (A *property* named ``title`` maps to a dict, not a string, so it is kept.)"""
    definitions = (schema.get("$defs") or {}) if isinstance(schema, dict) else {}

    def clean(node: Any, depth: int) -> Any:
        if isinstance(node, dict):
            reference = node.get("$ref")
            if isinstance(reference, str) and reference.startswith("#/$defs/") and depth < 32:
                target = definitions.get(reference.removeprefix("#/$defs/"), {})
                return clean({**target, **{k: v for k, v in node.items() if k != "$ref"}}, depth + 1)
            return {
                key: clean(value, depth)
                for key, value in node.items()
                if key != "$defs" and not (key == "title" and isinstance(value, str))
            }
        if isinstance(node, list):
            return [clean(value, depth) for value in node]
        return node

    return clean(schema, 0)
