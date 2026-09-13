"""One source of truth for how documents are chunked.

Chunk settings were resolved in two places. The upload route read the workspace's
RAG config and built its own chunker; the connector path constructed
``HierarchicalChunker()`` with library defaults. So the same workspace chunked
documents differently depending on how they arrived, and the connector path
ignored the settings entirely.

Both paths now resolve settings here. The workspace config is read through an
injected reader (registered at startup) so this module does not need to know how
that config is stored, and falls back to env-driven defaults when nothing is
registered - which is what unit tests and standalone use get.

Config (env, all optional):
  CHUNK_SIZE            default 512 characters per chunk
  CHUNK_OVERLAP_PERCENT default 12 (percent of chunk_size carried between chunks)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Optional

# Matches the bounds the RAG config API validates against, so a stored value can
# never produce a chunker the embedding step cannot handle.
MIN_CHUNK_SIZE, MAX_CHUNK_SIZE = 128, 2048
MAX_OVERLAP_PERCENT = 30


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


@dataclass(frozen=True)
class ChunkConfig:
    chunk_size: int
    chunk_overlap: int

    @property
    def stride(self) -> int:
        """How far the window advances. Guaranteed positive, so chunking always
        terminates even if overlap were configured up to the chunk size."""
        return max(1, self.chunk_size - self.chunk_overlap)


ConfigReader = Callable[[str, str], dict[str, Any]]
_reader: Optional[ConfigReader] = None


def set_config_reader(reader: Optional[ConfigReader]) -> None:
    """Register how to read a workspace's stored RAG config."""
    global _reader
    _reader = reader


def default_chunk_config() -> ChunkConfig:
    size = _clamp(_env_int("CHUNK_SIZE", 512), MIN_CHUNK_SIZE, MAX_CHUNK_SIZE)
    percent = _clamp(_env_int("CHUNK_OVERLAP_PERCENT", 12), 0, MAX_OVERLAP_PERCENT)
    return ChunkConfig(chunk_size=size, chunk_overlap=size * percent // 100)


def resolve_chunk_config(tenant_id: str = "", user_id: str = "") -> ChunkConfig:
    """The chunk settings in force for this workspace."""
    fallback = default_chunk_config()
    if _reader is None or not tenant_id:
        return fallback

    try:
        stored = _reader(tenant_id, user_id) or {}
    except Exception as err:
        print(f"[ChunkConfig] Could not read RAG config for {tenant_id}: {err}")
        return fallback

    size = _clamp(int(stored.get("chunk_size") or fallback.chunk_size), MIN_CHUNK_SIZE, MAX_CHUNK_SIZE)
    percent = _clamp(int(stored.get("overlap") or 0), 0, MAX_OVERLAP_PERCENT)
    return ChunkConfig(chunk_size=size, chunk_overlap=size * percent // 100)
