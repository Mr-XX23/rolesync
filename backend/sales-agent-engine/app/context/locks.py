"""State lock + versioning (implementation-plan §6): optimistic concurrency for memory.

A write reads the latest version ``v``, computes the new content from it and inserts version
``v + 1``. Two writers that read the same ``v`` both try to insert ``v + 1``; the database's
unique key lets exactly one succeed. The other re-reads and re-applies its change to the
winner's content (a merge), so neither update is lost and nothing is ever overwritten blindly.
Mutations are therefore functions of the current content, not precomputed values.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


class VersionConflict(Exception):
    """Another writer already stored the version this write was based on."""


class MemoryBusy(Exception):
    """A write kept colliding with other writers and gave up; the message is safe to show."""


async def with_optimistic_retry(write: Callable[[], Awaitable[T]], *, attempts: int = 8, base_delay: float = 0.005) -> T:
    """Run ``write`` (which re-reads before writing) until it doesn't hit a ``VersionConflict``."""
    for attempt in range(1, attempts + 1):
        try:
            return await write()
        except VersionConflict:
            if attempt == attempts:
                break
            # A little jitter so writers that collided don't collide again in lockstep.
            await asyncio.sleep(base_delay * attempt * (1 + random.random()))
    raise MemoryBusy("memory is being changed by others right now; try again in a moment")
