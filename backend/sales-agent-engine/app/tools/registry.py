"""Tool definitions and the per-agent scope map (implementation-plan §4)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from app.core.context import AgentContext
from app.tools.types import (
    ToolCategory,
    ToolInput,
    ToolInvocation,
    ToolKind,
    ToolOutput,
    ToolScope,
    UndoInvocation,
)

ToolHandler = Callable[[ToolInvocation], Awaitable[ToolOutput]]
AclCheck = Callable[[AgentContext, ToolInput], Awaitable[None]]  # raise ToolAccessDenied
# What the reviewer sees on the approval card. It may look things up (current prices, the
# stock level before a change) and may reject unusable arguments with ToolInputError, so
# the agent hears about them before anyone is asked to approve.
PreviewBuilder = Callable[[AgentContext, ToolInput], Awaitable[dict[str, Any]]]
# Reverses a completed write from the ``UndoPlan`` its handler returned; returns a summary.
UndoHandler = Callable[[UndoInvocation], Awaitable[str]]

# Which scopes each agent may use. The gate enforces this on every call, so e.g. the
# research agent is rejected when it tries a COMMUNICATION tool, whatever the model asks.
SCOPES: Mapping[str, frozenset[ToolScope]] = {
    # Sole coordinator: every scope, plus the only one that may hand work to a sub-agent.
    "orchestrator": frozenset(ToolScope),
    # Sub-agents (Phase 5). None of them has DELEGATE, so a sub-agent cannot start another.
    "research": frozenset({ToolScope.READ}),
    "outreach": frozenset({ToolScope.READ, ToolScope.COMMUNICATION}),
    "quote": frozenset({ToolScope.READ, ToolScope.CATALOG, ToolScope.DOCUMENT}),
}


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    kind: ToolKind
    scope: ToolScope
    category: ToolCategory
    input_model: type[ToolInput]
    handler: ToolHandler
    irreversible: bool = False  # autonomy envelope: always escalates
    timeout_seconds: float | None = None
    acl: AclCheck | None = None
    preview: PreviewBuilder | None = None
    undo_handler: UndoHandler | None = None
    # Attempts for transient failures. Default: reads retry, writes never do (a retry could
    # repeat the side effect); a write that is safe to repeat may opt in.
    max_attempts: int | None = None

    def __post_init__(self) -> None:
        if (self.kind is ToolKind.READ) != (self.scope is ToolScope.READ):
            raise ValueError(f"tool {self.name!r}: READ tools need scope READ and writes need a write scope")
        if (self.kind is ToolKind.MEMORY) != (self.scope is ToolScope.MEMORY):
            raise ValueError(f"tool {self.name!r}: MEMORY tools need scope MEMORY, and only they may have it")
        if (self.kind is ToolKind.DELEGATE) != (self.scope is ToolScope.DELEGATE):
            raise ValueError(f"tool {self.name!r}: DELEGATE tools need scope DELEGATE, and only they may have it")
        if self.kind is not ToolKind.WRITE and self.undo_handler is not None:
            raise ValueError(f"tool {self.name!r}: only a WRITE tool has something to undo")

    def parameters_schema(self) -> dict[str, Any]:
        return self.input_model.model_json_schema()

    async def build_preview(self, ctx: AgentContext, args: ToolInput) -> dict[str, Any]:
        if self.preview is not None:
            return await self.preview(ctx, args)
        return {"tool": self.name, "args": args.model_dump(mode="json")}


class ToolRegistry:
    def __init__(self, definitions: Iterable[ToolDefinition] = ()) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._tools:
            raise ValueError(f"tool {definition.name!r} registered twice")
        self._tools[definition.name] = definition

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def all(self) -> list[ToolDefinition]:
        return list(self._tools.values())


class AgentScopes:
    def __init__(self, scopes: Mapping[str, frozenset[ToolScope]] = SCOPES) -> None:
        self._scopes = dict(scopes)

    def allows(self, agent_name: str, definition: ToolDefinition) -> bool:
        return definition.scope in self._scopes.get(agent_name, frozenset())

    def tools_for(self, agent_name: str, registry: ToolRegistry) -> list[ToolDefinition]:
        return [d for d in registry.all() if self.allows(agent_name, d)]
