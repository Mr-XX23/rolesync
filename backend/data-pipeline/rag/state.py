"""Cached probe telling each store whether Postgres persistence is usable.

Probed once per process; stores fall back to in-memory behaviour when False so
a database outage degrades the pipeline instead of breaking ingestion.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from rag.database import persistence_disabled, session_scope

logger = logging.getLogger("rag.state")

_available: bool | None = None
_vector_index: bool | None = None


def set_persistence_available(value: bool) -> None:
    global _available
    _available = value


def set_vector_index_available(value: bool) -> None:
    """Recorded at startup: whether pgvector + the HNSW index are usable."""
    global _vector_index
    _vector_index = value


def vector_index_available() -> bool:
    """True when similarity search can use the pgvector HNSW index.

    Probed lazily so a store built at import time still sees the startup result.
    """
    global _vector_index
    if _vector_index is not None:
        return _vector_index

    if persistence_disabled():
        _vector_index = False
        return _vector_index

    try:
        with session_scope() as session:
            session.execute(text("SELECT 1 FROM rag.vector_chunks LIMIT 1"))
        _vector_index = True
    except Exception:
        _vector_index = False
    return _vector_index


def persistence_available(refresh: bool = False) -> bool:
    global _available
    if _available is not None and not refresh:
        return _available

    if persistence_disabled():
        _available = False
        return _available

    try:
        with session_scope() as session:
            session.execute(text("SELECT 1"))
        _available = True
    except Exception as err:
        logger.warning("RAG persistence probe failed; using in-memory stores: %s", err)
        _available = False
    return _available
