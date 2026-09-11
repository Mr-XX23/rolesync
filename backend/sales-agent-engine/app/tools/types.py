from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ValidationError

from app.core.context import AgentContext
from app.core.enums import ToolOutcome


class ToolKind(StrEnum):
    READ = "READ"  # never needs approval
    WRITE = "WRITE"  # approval (interactive) or inside the autonomy envelope


class ToolScope(StrEnum):
    """Capability a tool needs; agents are granted scopes in ``registry.SCOPES``."""

    READ = "READ"
    COMMUNICATION = "COMMUNICATION"  # send email, post message, calendar invite, notion write
    CATALOG = "CATALOG"  # catalog + inventory writes, reservations
    DOCUMENT = "DOCUMENT"  # document generation, drive / KB storage, quotes
    CRM = "CRM"  # deal records


class ToolCategory(StrEnum):
    COMMUNICATION = "communication"
    KNOWLEDGE = "knowledge"
    ACTION = "action"
    INTELLIGENCE = "intelligence"


class ToolInput(BaseModel):
    """Base for every tool's arguments. Unknown fields are rejected, so a model cannot
    smuggle identity (tenant, user) or anything else a tool doesn't declare."""

    model_config = {"extra": "forbid"}


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    ctx: AgentContext
    agent_name: str
    call_id: str
    args: ToolInput


@dataclass(frozen=True, slots=True)
class ToolOutput:
    """What a tool handler returns."""

    data: Any
    summary: str
    ref_id: str | None = None  # id of the created side effect, kept on the saga step


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What the gate returns to an agent."""

    ok: bool
    tool: str
    call_id: str
    outcome: ToolOutcome
    data: Any = None
    summary: str | None = None
    error: str | None = None
    pending_action_id: UUID | None = None
    duplicate: bool = False
    # The arguments the tool actually ran with: after a human edit these differ from what
    # the model proposed, and records of the action must reflect what really happened.
    executed_args: dict[str, Any] | None = None

    def for_model(self) -> dict[str, Any]:
        """The payload an LLM sees as the tool response."""
        payload: dict[str, Any] = {"ok": self.ok, "outcome": self.outcome.value}
        if self.summary:
            payload["summary"] = self.summary
        if self.data is not None:
            payload["data"] = self.data
        if self.error:
            payload["error"] = self.error
        return payload


class ToolAccessDenied(Exception):
    """Raised by an ACL check or handler: the caller may not touch this resource."""


class ToolInputError(Exception):
    """Raised by a handler for arguments that are well-typed but unusable."""


class ToolOutcomeUnknown(Exception):
    """Raised by a write handler that could not learn whether its side effect happened
    (e.g. the connection dropped after the request was sent). Never retried."""


def describe_validation_error(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc']) or 'arguments'}: {error['msg']}" for error in exc.errors()
    )
