"""Tool definitions and the per-agent scope map (implementation-plan §4)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from app.core.context import AgentContext
from app.tools.types import ToolCategory, ToolInput, ToolInvocation, ToolKind, ToolOutput, ToolScope

ToolHandler = Callable[[ToolInvocation], Awaitable[ToolOutput]]
AclCheck = Callable[[AgentContext, ToolInput], Awaitable[None]]  # raise ToolAccessDenied
PreviewBuilder = Callable[[ToolInput], dict[str, Any]]
UndoBuilder = Callable[[ToolInput], dict[str, Any] | None]

# Which scopes each agent may use. The gate enforces this on every call, so e.g. the
# research agent is rejected when it tries a COMMUNICATION tool, whatever the model asks.
SCOPES: Mapping[str, frozenset[ToolScope]] = {
    # Sole coordinator. Narrowed to reads + delegation once sub-agents own writes (Phase 5).
    "orchestrator": frozenset(ToolScope),
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
    undo: UndoBuilder | None = None

    def __post_init__(self) -> None:
        if (self.kind is ToolKind.READ) != (self.scope is ToolScope.READ):
            raise ValueError(f"tool {self.name!r}: READ tools need scope READ and writes need a write scope")

    def parameters_schema(self) -> dict[str, Any]:
        return self.input_model.model_json_schema()

    def build_preview(self, args: ToolInput) -> dict[str, Any]:
        if self.preview is not None:
            return self.preview(args)
        return {"tool": self.name, "args": args.model_dump(mode="json")}

    def build_undo(self, args: ToolInput) -> dict[str, Any] | None:
        return self.undo(args) if self.undo is not None else None


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
