"""Postgres persistence for the RAG ingestion pipeline.

Mirrors the catalog database bootstrap so the pipeline's canonical lineage,
chunk hashes and checkpoints survive a process restart instead of living in
per-process dictionaries.

Every consumer degrades gracefully: if Postgres is unreachable (local dev,
tests, a DB outage) the stores fall back to in-memory behaviour rather than
failing ingestion.
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from urllib.parse import urlparse, urlunparse

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger("rag.database")

Base = declarative_base()

RAG_SCHEMA = "rag"
DEFAULT_RAG_DB_NAME = "rolesync-micro-rag"
_FALLBACK_URL = f"postgresql://postgres:root@localhost:5432/{DEFAULT_RAG_DB_NAME}"


def get_database_url() -> str:
    """Resolve the RAG database URL.

    Order: explicit RAG_DATABASE_URL -> derived from CATALOG_DATABASE_URL (same
    server/credentials, different database) -> local fallback.
    """
    url = os.environ.get("RAG_DATABASE_URL", "").strip()
    if not url:
        catalog_url = os.environ.get("CATALOG_DATABASE_URL", "").strip()
        if catalog_url:
            try:
                parsed = urlparse(catalog_url)
                url = urlunparse(parsed._replace(path=f"/{DEFAULT_RAG_DB_NAME}"))
            except Exception:
                url = ""
    if not url:
        url = _FALLBACK_URL

    # Inside the container "localhost" is not the Postgres host.
    if os.path.exists("/.dockerenv") and "localhost" in url:
        url = url.replace("localhost", "postgres").replace("127.0.0.1", "postgres")
    return url


def persistence_disabled() -> bool:
    """Explicit opt-out used by tests and by anyone running without Postgres."""
    if os.environ.get("RAG_PERSISTENCE", "").strip().lower() in {"0", "off", "false", "disabled"}:
        return True
    # An explicitly blank RAG_DATABASE_URL means "do not persist".
    return "RAG_DATABASE_URL" in os.environ and not os.environ["RAG_DATABASE_URL"].strip()


def ensure_database_exists(db_url: str | None = None) -> None:
    """Create the RAG database if it does not exist yet."""
    if db_url is None:
        db_url = get_database_url()

    parsed = urlparse(db_url)
    target_db = parsed.path.lstrip("/")
    conn = psycopg2.connect(
        dbname="postgres",
        user=parsed.username or "postgres",
        password=parsed.password or "root",
        host=parsed.hostname or "localhost",
        port=parsed.port or 5432,
        connect_timeout=5,
    )
    try:
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (target_db,))
            if not cur.fetchone():
                cur.execute(f'CREATE DATABASE "{target_db}";')
                logger.info("Created database '%s'.", target_db)
    finally:
        conn.close()


_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            get_database_url(),
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            connect_args={"connect_timeout": 5},
        )
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())
    return _SessionLocal


@contextmanager
def session_scope():
    """Transactional session. Rolls back and re-raises so callers can fall back."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_rag_db() -> bool:
    """Create database, schema and tables. Returns True when persistence is live."""
    if persistence_disabled():
        logger.info("RAG persistence explicitly disabled; using in-memory stores.")
        return False
    try:
        ensure_database_exists()
        engine = get_engine()
        with engine.begin() as conn:
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {RAG_SCHEMA};"))
        from rag import models  # noqa: F401  (register models on Base)
        Base.metadata.create_all(bind=engine)
        logger.info("RAG database ready (schema '%s').", RAG_SCHEMA)
        return True
    except Exception as err:
        logger.warning("RAG persistence unavailable, falling back to in-memory stores: %s", err)
        return False
