from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Protocol

from app.models.types import StreamEvent, TaskSpec


class LLMProvider(Protocol):
    """One vendor behind the router. Swapping a vendor means replacing one implementation."""

    name: str

    def stream(self, task: TaskSpec, models: Sequence[str]) -> AsyncIterator[StreamEvent]:
        """Yield ``TextDelta``s then exactly one ``StreamDone``; raise ``ProviderError`` on failure.

        ``models`` is the ordered candidate list for this route; a provider may try them
        in order (OpenRouter does this natively) or use only the first.
        """
        ...
