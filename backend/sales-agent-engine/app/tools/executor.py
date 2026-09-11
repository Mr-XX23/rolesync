from __future__ import annotations

import asyncio

from app.tools.registry import ToolDefinition
from app.tools.types import ToolInvocation, ToolOutput


class ToolExecutor:
    """Runs a handler under a timeout. Retries, backoff and the circuit breaker are
    layered on here by the guardrails (Phase 3)."""

    def __init__(self, default_timeout_seconds: float) -> None:
        self._default_timeout = default_timeout_seconds

    async def run(self, definition: ToolDefinition, invocation: ToolInvocation) -> ToolOutput:
        async with asyncio.timeout(definition.timeout_seconds or self._default_timeout):
            return await definition.handler(invocation)
