"""Per-turn limits and loop detection: the run's circuit breaker (implementation-plan §8).

The orchestrator checks them before every model call and before running the calls a model
asked for. A breach halts the turn cleanly: the session ends HALTED with a message for the
rep and a ``halted`` event, instead of spinning until something else gives out. Delegation
depth joins these limits when sub-agents arrive (Phase 5).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


@dataclass(frozen=True, slots=True)
class TurnLimits:
    max_steps: int  # model calls per turn
    max_tool_calls: int  # tool calls per turn
    max_tokens: int  # model tokens per turn (input + output): the cost cap of one request
    max_identical_calls: int  # the same tool with the same arguments, per turn


class HaltReason(StrEnum):
    STEP_LIMIT = "STEP_LIMIT"
    TOOL_CALL_LIMIT = "TOOL_CALL_LIMIT"
    TOKEN_LIMIT = "TOKEN_LIMIT"
    LOOP = "LOOP"


@dataclass(frozen=True, slots=True)
class Halt:
    reason: HaltReason
    message: str  # for the rep

    def to_dict(self) -> dict[str, str]:
        return {"reason": self.reason.value, "message": self.message}


def fingerprint(tool: str, arguments: Mapping[str, Any] | None) -> str:
    """Identity of a call: the same tool with the same arguments (key order doesn't matter)."""
    canonical = json.dumps({"tool": tool, "args": arguments or {}}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def check_before_step(limits: TurnLimits, *, steps_taken: int, tokens_used: int) -> Halt | None:
    """Before a model call. ``steps_taken`` counts the calls already made this turn."""
    if steps_taken >= limits.max_steps:
        return Halt(
            HaltReason.STEP_LIMIT,
            f"I stopped after {limits.max_steps} steps without finishing this request, so it wouldn't run on "
            "indefinitely. Tell me how you'd like to continue.",
        )
    if tokens_used >= limits.max_tokens:
        return Halt(
            HaltReason.TOKEN_LIMIT,
            "I stopped because this request used up its processing budget. Tell me how you'd like to continue, "
            "or break it into smaller requests.",
        )
    return None


def check_calls(
    limits: TurnLimits,
    *,
    calls_made: int,
    seen: Mapping[str, int],
    calls: Sequence[tuple[str, Mapping[str, Any] | None]],
) -> tuple[Halt | None, dict[str, int]]:
    """Before running the calls a model asked for. Returns a halt (if any) and the updated
    count of each call's fingerprint this turn."""
    counts = dict(seen)
    for name, arguments in calls:
        key = fingerprint(name, arguments)
        counts[key] = counts.get(key, 0) + 1
        if counts[key] > limits.max_identical_calls:
            return (
                Halt(
                    HaltReason.LOOP,
                    f"I stopped because I kept repeating the same step ('{name}' with the same details) without "
                    "making progress. Tell me how you'd like to continue.",
                ),
                counts,
            )
    if calls_made + len(calls) > limits.max_tool_calls:
        return (
            Halt(
                HaltReason.TOOL_CALL_LIMIT,
                f"I stopped because this request needed more than {limits.max_tool_calls} tool calls. Tell me how "
                "you'd like to continue, or narrow the request down.",
            ),
            counts,
        )
    return None, counts
