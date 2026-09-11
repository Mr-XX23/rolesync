import os
import logging
from urllib.parse import urlparse
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger("catalog.database")

Base = declarative_base()


def get_database_url() -> str:
    url = os.environ.get(
        "CATALOG_DATABASE_URL",
        "postgresql://postgres:root@localhost:5432/rolesync-micro-catalog",
    )
    # If inside docker container and pointing to localhost, switch to postgres service host
    if os.path.exists("/.dockerenv") and "localhost" in url:
        url = url.replace("localhost", "postgres").replace("127.0.0.1", "postgres")
    return url


def ensure_database_exists(db_url: str | None = None) -> None:
    """Ensure the target database exists; if not, create it via postgres maintenance DB."""
    if db_url is None:
        db_url = get_database_url()

    parsed = urlparse(db_url)
    target_db = parsed.path.lstrip("/")
    user = parsed.username or "postgres"
    password = parsed.password or "root"
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432

    # Connect to default maintenance database
    try:
        conn = psycopg2.connect(
            dbname="postgres",
            user=user,
            password=password,
            host=host,
            port=port,
            connect_timeout=5,
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s;",
                (target_db,),
            )
            exists = cur.fetchone()
            if not exists:
                logger.info(f"Database '{target_db}' does not exist. Creating...")
                # Note: database name cannot be parameterized in CREATE DATABASE
                cur.execute(f'CREATE DATABASE "{target_db}";')
                logger.info(f"Database '{target_db}' created successfully.")
            else:
                logger.info(f"Database '{target_db}' already exists.")
        conn.close()
    except Exception as e:
        logger.warning(f"ensure_database_exists encountered an error: {e}")


_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        db_url = get_database_url()
        _engine = create_engine(
            db_url,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
        )
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=get_engine(),
        )
    return _SessionLocal


def SessionLocal():
    return get_session_factory()()


def ensure_catalog_schema(engine=None) -> None:
    if engine is None:
        engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS catalog;"))
    logger.info("Schema 'catalog' verified/created.")


def init_catalog_db() -> None:
    """Complete initialization: DB creation, schema creation, tables, indexes, and availability view."""
    try:
        ensure_database_exists()
    except Exception as e:
        logger.warning(f"Could not auto-create database (may already exist): {e}")

    engine = get_engine()
    ensure_catalog_schema(engine)

    from catalog.migrations import run_migrations
    run_migrations(engine)
    logger.info("Catalog database initialization complete.")


def get_catalog_db():
    """FastAPI dependency for obtaining catalog database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
