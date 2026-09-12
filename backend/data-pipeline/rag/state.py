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


def set_persistence_available(value: bool) -> None:
    global _available
    _available = value


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
