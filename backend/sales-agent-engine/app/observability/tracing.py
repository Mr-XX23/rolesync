"""``TracingClient``: the only tracing surface business logic sees.

Traces (reasoning, tool timings, model choices) are for debugging/replay and are
distinct from ``agent.audit``. The LangSmith implementation is added behind this
interface; ``NoopTracingClient`` keeps everything working without a key.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any, Protocol


class Span(Protocol):
    def set_outputs(self, outputs: Mapping[str, Any]) -> None: ...

    def set_error(self, error: BaseException) -> None: ...


class TracingClient(Protocol):
    def span(
        self,
        name: str,
        *,
        kind: str,
        inputs: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Any:  # async context manager yielding a Span
        ...


class _NoopSpan:
    def set_outputs(self, outputs: Mapping[str, Any]) -> None:
        pass

    def set_error(self, error: BaseException) -> None:
        pass


class NoopTracingClient:
    @asynccontextmanager
    async def span(
        self,
        name: str,
        *,
        kind: str,
        inputs: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AsyncIterator[Span]:
        yield _NoopSpan()
