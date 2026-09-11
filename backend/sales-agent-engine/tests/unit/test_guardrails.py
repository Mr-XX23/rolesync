"""Per-call guardrails (retries, timeout, circuit breaker) and per-turn limits + loop detection."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from pydantic import Field

from app.core.context import AgentContext, RunMode
from app.engine.guardrails.limits import HaltReason, TurnLimits, check_before_step, check_calls, fingerprint
from app.tools.executor import CircuitBreaker, ToolExecutor, ToolUnavailable
from app.tools.registry import ToolDefinition
from app.tools.types import (
    ToolAccessDenied,
    ToolCategory,
    ToolFailed,
    ToolInput,
    ToolInputError,
    ToolInvocation,
    ToolKind,
    ToolOutput,
    ToolScope,
    UndoInvocation,
)

CTX = AgentContext(tenant_id=uuid4(), user_id=uuid4(), session_id=uuid4(), mode=RunMode.INTERACTIVE)


class Args(ToolInput):
    value: str = Field(default="x")


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _tool(kind: ToolKind, handler, *, timeout: float | None = None, undo=None) -> ToolDefinition:
    return ToolDefinition(
        name="flaky",
        description="",
        kind=kind,
        scope=ToolScope.READ if kind is ToolKind.READ else ToolScope.COMMUNICATION,
        category=ToolCategory.KNOWLEDGE,
        input_model=Args,
        handler=handler,
        timeout_seconds=timeout,
        undo_handler=undo,
    )


class Script:
    """A handler that raises the scripted errors in order, then succeeds."""

    def __init__(self, *errors: BaseException) -> None:
        self.errors = list(errors)
        self.calls = 0

    async def __call__(self, invocation) -> ToolOutput:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return ToolOutput(data={"ok": True}, summary="done")


def _executor(clock: Clock | None = None, *, threshold: int = 5) -> tuple[ToolExecutor, list[float]]:
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    breaker = CircuitBreaker(threshold=threshold, cooldown_seconds=30, clock=clock or Clock())
    return ToolExecutor(5.0, read_attempts=3, backoff_seconds=0.5, breaker=breaker, sleep=sleep), sleeps


def _invocation() -> ToolInvocation:
    return ToolInvocation(CTX, "orchestrator", "c1", Args())


async def test_reads_retry_transient_failures_with_exponential_backoff():
    handler = Script(ToolFailed("503", retryable=True), ToolFailed("connection reset", retryable=True))
    executor, sleeps = _executor()

    output = await executor.run(_tool(ToolKind.READ, handler), _invocation())

    assert output.summary == "done" and handler.calls == 3
    assert sleeps == [0.5, 1.5]


async def test_retries_are_bounded():
    handler = Script(*(ToolFailed("503", retryable=True) for _ in range(5)))
    executor, sleeps = _executor()

    with pytest.raises(ToolFailed, match="503"):
        await executor.run(_tool(ToolKind.READ, handler), _invocation())
    assert handler.calls == 3 and len(sleeps) == 2


@pytest.mark.parametrize(
    "error", [ToolFailed("the upstream said no"), ToolInputError("bad sku"), ToolAccessDenied("not connected")]
)
async def test_failures_about_the_request_are_not_retried(error):
    handler = Script(error)
    executor, sleeps = _executor()

    with pytest.raises(type(error)):
        await executor.run(_tool(ToolKind.READ, handler), _invocation())
    assert handler.calls == 1 and sleeps == []


async def test_writes_are_never_retried_even_when_the_failure_looks_transient():
    handler = Script(ToolFailed("503", retryable=True))
    executor, sleeps = _executor()

    with pytest.raises(ToolFailed):
        await executor.run(_tool(ToolKind.WRITE, handler), _invocation())
    assert handler.calls == 1 and sleeps == []


async def test_a_timeout_is_not_retried():
    async def slow(invocation) -> ToolOutput:
        await asyncio.sleep(5)
        raise AssertionError("unreachable")

    executor, sleeps = _executor()
    with pytest.raises(TimeoutError):
        await executor.run(_tool(ToolKind.READ, slow, timeout=0.05), _invocation())
    assert sleeps == []


async def test_undo_steps_retry_transient_failures():
    attempts = 0

    async def undo(invocation: UndoInvocation) -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise ToolFailed("no answer", retryable=True)
        return "undone"

    executor, _ = _executor()
    definition = _tool(ToolKind.WRITE, Script(), undo=undo)
    assert await executor.run_undo(definition, UndoInvocation(CTX, {"id": 1})) == "undone"
    assert attempts == 2


async def test_the_circuit_opens_after_repeated_transient_failures_and_fails_fast():
    clock = Clock()
    executor, _ = _executor(clock, threshold=3)
    broken = Script(*(TimeoutError() for _ in range(10)))
    definition = _tool(ToolKind.WRITE, broken)

    for _ in range(3):
        with pytest.raises(TimeoutError):
            await executor.run(definition, _invocation())
    with pytest.raises(ToolUnavailable, match="temporarily unavailable"):
        await executor.run(definition, _invocation())
    assert broken.calls == 3  # the fourth call never reached the tool

    # After the cool-down one probe goes through; while it is out, others still fail fast.
    clock.now += 31
    healthy = Script()
    probe = _tool(ToolKind.WRITE, healthy)
    assert (await executor.run(probe, _invocation())).summary == "done"
    assert (await executor.run(probe, _invocation())).summary == "done"  # closed again
    assert healthy.calls == 2


async def test_a_failed_probe_reopens_the_circuit():
    clock = Clock()
    executor, _ = _executor(clock, threshold=1)
    definition = _tool(ToolKind.WRITE, Script(ToolFailed("down", retryable=True), ToolFailed("still down", retryable=True)))

    with pytest.raises(ToolFailed):
        await executor.run(definition, _invocation())
    clock.now += 31
    with pytest.raises(ToolFailed, match="still down"):
        await executor.run(definition, _invocation())
    with pytest.raises(ToolUnavailable):
        await executor.run(definition, _invocation())


async def test_errors_about_the_request_never_trip_the_circuit():
    executor, _ = _executor(threshold=2)
    definition = _tool(ToolKind.WRITE, Script(*(ToolAccessDenied("not connected") for _ in range(5))))
    for _ in range(5):
        with pytest.raises(ToolAccessDenied):
            await executor.run(definition, _invocation())


def test_a_breaker_probe_that_never_reports_back_stops_blocking_after_a_cool_down():
    clock = Clock()
    breaker = CircuitBreaker(threshold=1, cooldown_seconds=30, clock=clock)
    breaker.failed("tool")
    clock.now += 31
    breaker.check("tool")  # the probe is let through ... and its run is cancelled
    with pytest.raises(ToolUnavailable):
        breaker.check("tool")
    clock.now += 31
    breaker.check("tool")  # a new probe


LIMITS = TurnLimits(max_steps=3, max_tool_calls=5, max_tokens=1000, max_identical_calls=2)


def test_fingerprints_ignore_argument_order():
    assert fingerprint("search", {"a": 1, "b": [1, 2]}) == fingerprint("search", {"b": [1, 2], "a": 1})
    assert fingerprint("search", {"a": 1}) != fingerprint("search", {"a": 2}) != fingerprint("other", {"a": 1})


def test_step_and_token_limits_halt_before_the_next_model_call():
    assert check_before_step(LIMITS, steps_taken=2, tokens_used=999) is None
    assert check_before_step(LIMITS, steps_taken=3, tokens_used=0).reason is HaltReason.STEP_LIMIT
    assert check_before_step(LIMITS, steps_taken=0, tokens_used=1000).reason is HaltReason.TOKEN_LIMIT


def test_the_third_identical_call_in_a_turn_is_a_loop():
    call = [("search_emails", {"query": "acme"})]
    halt, seen = check_calls(LIMITS, calls_made=0, seen={}, calls=call)
    assert halt is None
    halt, seen = check_calls(LIMITS, calls_made=1, seen=seen, calls=call)
    assert halt is None
    halt, _ = check_calls(LIMITS, calls_made=2, seen=seen, calls=call)
    assert halt is not None and halt.reason is HaltReason.LOOP and "search_emails" in halt.message
    # Different arguments are different work.
    halt, _ = check_calls(LIMITS, calls_made=2, seen=seen, calls=[("search_emails", {"query": "globex"})])
    assert halt is None


def test_too_many_tool_calls_in_a_turn_halt():
    calls = [("lookup", {"n": index}) for index in range(3)]
    assert check_calls(LIMITS, calls_made=2, seen={}, calls=calls)[0] is None
    halt, _ = check_calls(LIMITS, calls_made=3, seen={}, calls=calls)
    assert halt is not None and halt.reason is HaltReason.TOOL_CALL_LIMIT
