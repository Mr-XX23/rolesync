"""The autonomy policy envelope: act alone vs. escalate to a human (implementation-plan §7).

The gate consults the policy for every write in AUTONOMOUS mode. Until the real
envelope exists (Phase 6), ``EscalateAllPolicy`` sends every autonomous write to a
human, which is the safe direction to be wrong in.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from app.core.context import AgentContext
from app.tools.types import ToolInput

if TYPE_CHECKING:
    from app.tools.registry import ToolDefinition


class Verdict(StrEnum):
    ALLOW = "ALLOW"  # inside the envelope: act alone
    ESCALATE = "ESCALATE"  # outside: pause for a human, even mid-campaign


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    verdict: Verdict
    reason: str


class AutonomyPolicy(Protocol):
    async def evaluate(self, ctx: AgentContext, tool: ToolDefinition, args: ToolInput) -> PolicyDecision: ...


class EscalateAllPolicy:
    async def evaluate(self, ctx: AgentContext, tool: ToolDefinition, args: ToolInput) -> PolicyDecision:
        return PolicyDecision(Verdict.ESCALATE, "autonomy envelope not configured; every write needs a human")
