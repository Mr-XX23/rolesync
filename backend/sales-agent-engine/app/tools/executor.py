"""Runs tool handlers under the per-call guardrails (implementation-plan §8).

- Timeout per call: the tool's own, or the default.
- Bounded retries with exponential backoff for failures that are quick and transient (the
  upstream refused the connection, answered 5xx or rate-limited). Reads and undo steps
  retry; writes never do, because repeating one could repeat its side effect. A timeout is
  not retried: the upstream is slow or down, and waiting again only stalls the run.
- A circuit breaker per tool: after repeated transient failures the tool fails fast for a
  cool-down instead of making every run wait out its timeouts, so one dead tool degrades a
  run instead of stalling it. Errors about the request itself (access, bad input, a business
  rule) mean the tool answered, so they never trip it.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from app.platform.langgraph_runtime import is_control_flow_signal
from app.tools.registry import ToolDefinition
from app.tools.types import ToolFailed, ToolInvocation, ToolKind, ToolOutcomeUnknown, ToolOutput, UndoInvocation

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ToolUnavailable(ToolFailed):
    """The tool's circuit is open: it failed repeatedly and is resting."""


@dataclass
class _Circuit:
    failures: int = 0
    opened_at: float | None = None
    probe_started: float | None = None


class CircuitBreaker:
    """Consecutive transient failures per tool (in this process). ``threshold`` failures open
    the circuit for ``cooldown_seconds``; then a single probe call is let through, and its
    result closes or re-opens it."""

    def __init__(self, *, threshold: int, cooldown_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._threshold = max(1, threshold)
        self._cooldown = cooldown_seconds
        self._clock = clock
        self._circuits: dict[str, _Circuit] = {}

    def check(self, name: str) -> None:
        circuit = self._circuits.get(name)
        if circuit is None or circuit.opened_at is None:
            return
        now = self._clock()
        remaining = self._cooldown - (now - circuit.opened_at)
        # A probe that never reported back (its run was cancelled) stops blocking after a cool-down.
        probe_in_flight = circuit.probe_started is not None and now - circuit.probe_started < self._cooldown
        if remaining > 0 or probe_in_flight:
            wait = max(1, round(remaining))
            raise ToolUnavailable(
                f"'{name}' is temporarily unavailable after repeated failures; try again in about {wait}s "
                "or continue without it"
            )
        circuit.probe_started = now  # half-open: this call is the probe

    def answered(self, name: str) -> None:
        """The tool responded (successfully, or with an error about the request)."""
        self._circuits.pop(name, None)

    def failed(self, name: str) -> None:
        circuit = self._circuits.setdefault(name, _Circuit())
        circuit.failures += 1
        circuit.probe_started = None
        if circuit.opened_at is not None or circuit.failures >= self._threshold:
            if circuit.opened_at is None:
                logger.warning("circuit opened for tool %s after %d failures", name, circuit.failures)
            circuit.opened_at = self._clock()

    def is_open(self, name: str) -> bool:
        circuit = self._circuits.get(name)
        return circuit is not None and circuit.opened_at is not None


class ToolExecutor:
    def __init__(
        self,
        default_timeout_seconds: float,
        *,
        read_attempts: int = 3,
        backoff_seconds: float = 0.5,
        breaker: CircuitBreaker | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._default_timeout = default_timeout_seconds
        self._read_attempts = max(1, read_attempts)
        self._backoff = backoff_seconds
        self._breaker = breaker or CircuitBreaker(threshold=5, cooldown_seconds=30.0)
        self._sleep = sleep

    async def run(self, definition: ToolDefinition, invocation: ToolInvocation) -> ToolOutput:
        default_attempts = self._read_attempts if definition.kind is ToolKind.READ else 1
        attempts = definition.max_attempts or default_attempts
        return await self._call(definition, lambda: definition.handler(invocation), attempts)

    async def run_undo(self, definition: ToolDefinition, invocation: UndoInvocation) -> str:
        """Undo steps are written to be safe to repeat (deleting what is already gone is a no-op)."""
        handler = definition.undo_handler
        if handler is None:
            raise ToolFailed(f"'{definition.name}' has no undo")
        return await self._call(definition, lambda: handler(invocation), self._read_attempts)

    async def _call(self, definition: ToolDefinition, call: Callable[[], Awaitable[T]], attempts: int) -> T:
        name = definition.name
        for attempt in range(1, attempts + 1):
            self._breaker.check(name)
            try:
                async with asyncio.timeout(definition.timeout_seconds or self._default_timeout):
                    result = await call()
            except Exception as exc:
                if is_control_flow_signal(exc):
                    raise
                if not _is_transient(exc):
                    self._breaker.answered(name)
                    raise
                self._breaker.failed(name)
                retryable = isinstance(exc, ToolFailed) and exc.retryable and not isinstance(exc, ToolUnavailable)
                if not retryable or attempt >= attempts:
                    raise
                delay = self._backoff * (3 ** (attempt - 1))
                logger.info("tool %s failed transiently (attempt %d/%d); retrying in %.1fs: %s", name, attempt, attempts, delay, exc)
                await self._sleep(delay)
            else:
                self._breaker.answered(name)
                return result
        raise AssertionError("unreachable")  # pragma: no cover


def _is_transient(exc: BaseException) -> bool:
    """Failures that say the tool (or what is behind it) is unhealthy, not that the request was wrong."""
    if isinstance(exc, ToolUnavailable):
        return False  # already counted when the circuit opened
    if isinstance(exc, ToolFailed):
        return exc.retryable
    return isinstance(exc, TimeoutError | ToolOutcomeUnknown | OSError)
