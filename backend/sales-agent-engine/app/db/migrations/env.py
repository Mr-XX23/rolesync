"""Alembic environment for schema ``agent`` (async engine).

Run from the service root:  ``alembic upgrade head``
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import AGENT_SCHEMA, CHECKPOINT_SCHEMA, get_settings
from app.db import models  # noqa: F401  (register tables on Base.metadata)
from app.db.base import Base

config = context.config
if config.config_file_name is not None and not config.attributes.get("skip_logging_config"):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url():
    # Tests (and tooling) may inject an explicit URL; otherwise use service settings.
    return config.attributes.get("sqlalchemy_url") or get_settings().sqlalchemy_url


def _include_object(obj, name, type_, reflected, compare_to):
    # LangGraph owns its checkpoint tables in their own schema; never diff them.
    if type_ == "table" and getattr(obj, "schema", None) not in (AGENT_SCHEMA,):
        return False
    return True


def _run(connection: Connection) -> None:
    # The version table lives in schema `agent`, so the schemas must exist first.
    connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{AGENT_SCHEMA}"'))
    connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{CHECKPOINT_SCHEMA}"'))
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_object=_include_object,
        version_table_schema=AGENT_SCHEMA,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_run)
        await connection.commit()
    await engine.dispose()


def run_migrations_offline() -> None:
    context.configure(
        url=str(_url()),
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        version_table_schema=AGENT_SCHEMA,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
elif config.attributes.get("connection") is not None:
    _run(config.attributes["connection"])
else:
    asyncio.run(run_migrations_online())
