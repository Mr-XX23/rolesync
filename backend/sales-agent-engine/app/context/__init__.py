"""Shared context + memory (implementation-plan §6): the only surface agents use for state
that outlives a model call. ``manager`` keeps prompts within budget (summaries, offloaded
tool results, what is known about the rep); ``stores`` holds versioned memory; ``locks``
is the optimistic-concurrency rule every memory write follows."""
