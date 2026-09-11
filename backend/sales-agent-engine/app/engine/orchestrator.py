"""The orchestrator: sole coordinator of a session (implementation-plan §0.4, §10 Phase 1).

    plan ──(tool calls?)──► act ──(more calls?)──► act ─ … ─► plan ─ … ─► END

- ``plan`` asks the model router for the next step and streams its tokens to the session.
- ``act`` runs exactly ONE pending tool call through the Tool Gate per super-step. A run
  that pauses for approval therefore resumes by re-running only that call, and the
  gate turns the re-run into a lookup (see ``langgraph_runtime``).
"""

from __future__ import annotations

import json
import operator
import time
from typing import Annotated, Any, TypedDict

from app.core.clock import utcnow
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
from app.platform.langgraph_runtime import END, GraphSpec, current_context
from app.tools.gate import ToolGate
from app.tools.registry import AgentScopes, ToolRegistry
from app.tools.types import ToolKind

AGENT_NAME = "orchestrator"

SYSTEM_PROMPT = """You are RoleSync's sales assistant. You work for one sales rep inside their workspace.

How to work:
- Use the tools to take action. Never say an action happened unless its tool result has outcome EXECUTED.
- Actions that affect the outside world (such as sending email) automatically pause for the rep's approval.
  Call the tool directly with complete, final content; do not ask for permission in chat first.
- If an action is REJECTED, do not retry it unchanged: ask what the rep wants changed.
  If it FAILED or was DENIED, say so briefly and suggest a next step.
- Write in clear, professional, friendly language. Keep chat replies short.

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
            messages=tuple(Message.from_dict(item) for item in history),
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
        call, *remaining = state["pending_calls"]
        arguments = call.get("arguments") or {}
        result = await self._gate.call_tool(ctx, AGENT_NAME, call["name"], arguments, call_id=call["gate_call_id"])

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
        reply = Message(
            role=Role.TOOL, content=json.dumps(result.for_model()), tool_call_id=call["id"], name=call["name"]
        )
        return {"messages": [reply.to_dict()], "pending_calls": remaining}

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
