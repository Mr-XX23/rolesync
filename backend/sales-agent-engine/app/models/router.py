"""Model router (implementation-plan §5): complexity picks the route, Gemini failure fails
over to OpenRouter. Every agent asks the router for a brain; nothing calls a provider
directly, so routing lives in one place and providers stay swappable.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass

from app.models.providers.base import LLMProvider
from app.models.types import (
    Complexity,
    Completion,
    ProviderError,
    ProviderUnavailable,
    StreamDone,
    StreamEvent,
    StreamRestart,
    TaskSpec,
    TextDelta,
)
from app.observability.tracing import TracingClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Route:
    provider: str
    models: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RoutingRules:
    complex: Route  # Gemini
    simple: Route  # OpenRouter
    failover: Route  # OpenRouter, used when the complex route fails

    def routes_for(self, complexity: Complexity) -> Sequence[Route]:
        if complexity is Complexity.HIGH:
            return (self.complex, self.failover)
        return (self.simple,)


class ModelRouter:
    def __init__(self, providers: Mapping[str, LLMProvider], rules: RoutingRules, tracer: TracingClient) -> None:
        self._providers = dict(providers)
        self._rules = rules
        self._tracer = tracer

    async def complete(self, task: TaskSpec) -> Completion:
        async for event in self.stream(task):
            if isinstance(event, StreamDone):
                return event.completion
        raise ProviderError("model stream ended without a completion")

    async def stream(self, task: TaskSpec) -> AsyncIterator[StreamEvent]:
        routes = [route for route in self._rules.routes_for(task.complexity) if route.provider in self._providers]
        if not routes:
            raise ProviderUnavailable(f"no configured provider for {task.complexity.value}-complexity tasks")

        for position, route in enumerate(routes):
            has_fallback = position + 1 < len(routes)
            emitted_text = False
            try:
                async with self._tracer.span(
                    f"llm:{task.purpose}",
                    kind="llm",
                    inputs={"messages": [m.to_dict() for m in task.messages], "system": task.system},
                    metadata={"provider": route.provider, "models": list(route.models), "complexity": task.complexity.value},
                ) as span:
                    async for event in self._providers[route.provider].stream(task, route.models):
                        if isinstance(event, TextDelta):
                            emitted_text = True
                        elif isinstance(event, StreamDone):
                            span.set_outputs(
                                {
                                    "message": event.completion.message.to_dict(),
                                    "model": event.completion.model,
                                    "usage": {
                                        "input_tokens": event.completion.usage.input_tokens,
                                        "output_tokens": event.completion.usage.output_tokens,
                                    },
                                }
                            )
                        yield event
                return
            except ProviderError as exc:
                if not has_fallback:
                    raise
                logger.warning("%s failed for %s, failing over: %s", route.provider, task.purpose, exc)
                if emitted_text:
                    yield StreamRestart(reason=f"{route.provider} failed mid-answer; retrying on {routes[position + 1].provider}")
