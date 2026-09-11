"""``TracingClient``: the only tracing surface business logic sees.

Traces (reasoning, model choices, tool timings) are for debugging and replay; they are
distinct from ``agent.audit``, which records actions for compliance. LangSmith sits
behind this interface, and ``NoopTracingClient`` keeps everything working without a key.
Spans nest through context variables: a session run contains its LLM and tool spans.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class Span(Protocol):
    def set_outputs(self, outputs: Mapping[str, Any]) -> None: ...


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


_RUN_TYPES = {"llm": "llm", "tool": "tool"}


class _LangSmithSpan:
    def __init__(self, run: Any) -> None:
        self._run = run

    def set_outputs(self, outputs: Mapping[str, Any]) -> None:
        self._run.add_outputs(dict(outputs))


class LangSmithTracingClient:
    def __init__(self, *, api_key: str, project: str, endpoint: str | None = None) -> None:
        from langsmith import Client

        self._client = Client(api_key=api_key, api_url=endpoint) if endpoint else Client(api_key=api_key)
        self._project = project

    @asynccontextmanager
    async def span(
        self,
        name: str,
        *,
        kind: str,
        inputs: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AsyncIterator[Span]:
        from langsmith import trace

        # Exceptions propagate through `trace`, which records them on the run.
        async with trace(
            name,
            run_type=_RUN_TYPES.get(kind, "chain"),
            inputs=dict(inputs or {}),
            metadata=dict(metadata or {}),
            project_name=self._project,
            client=self._client,
        ) as run:
            yield _LangSmithSpan(run)

    def flush(self) -> None:
        try:
            self._client.flush()
        except Exception:
            logger.warning("could not flush LangSmith traces", exc_info=True)
