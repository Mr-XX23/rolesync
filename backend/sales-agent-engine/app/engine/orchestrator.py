"""The orchestrator: sole coordinator of a session (implementation-plan §0.4, §10 Phase 1).

    plan ──(tool calls?)──► act ──(more calls?)──► act ─ … ─► plan ─ … ─► END

- ``plan`` asks the model router for the next step and streams its tokens to the session.
- ``act`` runs pending tool calls through the Tool Gate: ONE write per super-step, so a
  run that pauses for approval resumes by re-running only that call (the gate turns the
  re-run into a lookup, see ``langgraph_runtime``). Consecutive reads can't pause and have
  no side effects, so they run together in one step.
"""

from __future__ import annotations

import asyncio
import json
import logging
import operator
import time
from typing import Annotated, Any, TypedDict

from app.core.clock import utcnow
from app.core.context import AgentContext
from app.core.enums import ToolOutcome
from app.engine.events import EventEmitter, EventType, emit_best_effort
from app.engine.workspace_record import WorkspaceRecorder
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
- Actions that affect the outside world (such as sending email) automatically pause for the rep's approval.
  Call the tool directly with complete, final content; do not ask for permission in chat first.
- If an action is REJECTED, do not retry it unchanged: ask what the rep wants changed.
  If it FAILED or was DENIED, say so briefly and suggest a next step (for example, connecting an app).
- If an action's outcome is UNKNOWN it may already have happened: never retry it. Tell the rep and ask
  them to check (for email, their Sent folder).

Research and answers:
- Reading never needs approval. Before answering questions about prospects, customers, products or the rep's
  own history, gather facts with the read tools, and use every source the question spans (web, emails,
  calendar, Slack, Notion, knowledge base, catalog). Request independent reads together in one step.
- Base answers only on tool results. Cite web facts with their URLs and name the documents, emails or messages
  you used. If something wasn't found, say so instead of guessing.
- When a source finds nothing, try at most one differently worded search there, then report it as not found.
  Don't retry sources that were DENIED (for example, an app that isn't connected).
- Prices, discounts and stock come only from the catalog tools.

Write in clear, professional, friendly language. Keep chat replies short unless the rep asks for detail.

Today is {today} (UTC)."""

_TOKEN_FLUSH_CHARS = 64
_TOKEN_FLUSH_SECONDS = 0.1


class OrchestratorState(TypedDict, total=False):
    messages: Annotated[list[dict[str, Any]], operator.add]
    pending_calls: list[dict[str, Any]]
    steps: int
    final_answer: str | None


def turn_input(user_message: str) -> dict[str, Any]:
    """Graph input for a new user turn (also resets per-turn bookkeeping)."""
    return {
        "messages": [Message(role=Role.USER, content=user_message).to_dict()],
        "pending_calls": [],
        "steps": 0,
        "final_answer": None,
    }


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
        max_steps: int,
    ) -> None:
        self._router = router
        self._gate = gate
        self._registry = registry
        self._scopes = scopes
        self._events = events
        self._recorder = recorder
        self._max_steps = max_steps

    def graph_spec(self) -> GraphSpec:
        return GraphSpec(
            state_schema=OrchestratorState,
            nodes={"plan": self.plan, "act": self.act},
            entry="plan",
            routers=[
                ("plan", _after_plan, {"act": "act", "end": END}),
                ("act", _after_act, {"act": "act", "plan": "plan"}),
            ],
        )

    async def plan(self, state: dict[str, Any]) -> dict[str, Any]:
        ctx = current_context()
        steps = int(state.get("steps") or 0) + 1
        history = state.get("messages") or []
        if steps > self._max_steps:
            text = (
                f"I stopped after {self._max_steps} steps without finishing this request. "
                "Tell me how you'd like to continue."
            )
            return {
                "messages": [Message(role=Role.ASSISTANT, content=text).to_dict()],
                "pending_calls": [],
                "steps": steps,
                "final_answer": text,
            }

        await emit_best_effort(self._events, ctx.session_id, EventType.STEP_STARTED, {"step": "planning", "number": steps})
        task = TaskSpec(
            purpose="plan",
            system=SYSTEM_PROMPT.format(today=utcnow().date().isoformat()),
            messages=repair_history([Message.from_dict(item) for item in history]),
            tools=self._tool_specs(),
            complexity=Complexity.HIGH,
        )
        completion = await self._stream(ctx.session_id, task)
        message = completion.message
        # The gate's idempotency key must be unique per session even if a model reuses its
        # own call ids across turns, so prefix it with the history position (stable on replay).
        position = len(history)
        calls = [
            {**call.to_dict(), "gate_call_id": f"{position}-{index}-{call.id}"}
            for index, call in enumerate(message.tool_calls)
        ]
        return {
            "messages": [message.to_dict()],
            "pending_calls": calls,
            "steps": steps,
            "final_answer": None if calls else message.content,
        }

    async def act(self, state: dict[str, Any]) -> dict[str, Any]:
        ctx = current_context()
        pending = state["pending_calls"]
        batch = self._next_batch(pending)
        replies = await asyncio.gather(*(self._run_call(ctx, call) for call in batch))
        return {"messages": [reply.to_dict() for reply in replies], "pending_calls": pending[len(batch) :]}

    def _next_batch(self, pending: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The next call alone, or, if it is a read, it and the reads directly after it."""
        batch: list[dict[str, Any]] = []
        for call in pending:
            definition = self._registry.get(call["name"])
            is_read = definition is not None and definition.kind is ToolKind.READ
            if batch and not is_read:
                break
            batch.append(call)
            if not is_read:
                break
        return batch

    async def _run_call(self, ctx: AgentContext, call: dict[str, Any]) -> Message:
        arguments = call.get("arguments") or {}
        try:
            result = await self._gate.call_tool(ctx, AGENT_NAME, call["name"], arguments, call_id=call["gate_call_id"])
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

        definition = self._registry.get(call["name"])
        if definition is not None and definition.kind is ToolKind.WRITE:
            await self._recorder.action_finished(
                ctx,
                idempotency_key=f"{ctx.session_id}:{call['gate_call_id']}",
                agent=AGENT_NAME,
                tool=call["name"],
                args=result.executed_args or arguments,  # a reviewer may have edited them
                result=result,
            )
        return Message(role=Role.TOOL, content=json.dumps(result.for_model()), tool_call_id=call["id"], name=call["name"])

    def _tool_specs(self) -> tuple[ToolSpec, ...]:
        return tuple(
            ToolSpec(name=d.name, description=d.description, parameters=_clean_schema(d.parameters_schema()))
            for d in self._scopes.tools_for(AGENT_NAME, self._registry)
        )

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


def _after_plan(state: dict[str, Any]) -> str:
    return "act" if state.get("pending_calls") else "end"


def _after_act(state: dict[str, Any]) -> str:
    return "act" if state.get("pending_calls") else "plan"


def _clean_schema(schema: Any) -> Any:
    """Drop Pydantic's cosmetic ``title`` annotations; models only need the structure.
    (A *property* named ``title`` maps to a dict, not a string, so it is kept.)"""
    if isinstance(schema, dict):
        return {
            key: _clean_schema(value)
            for key, value in schema.items()
            if not (key == "title" and isinstance(value, str))
        }
    if isinstance(schema, list):
        return [_clean_schema(value) for value in schema]
    return schema
