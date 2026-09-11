from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import AGENT_SCHEMA

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(schema=AGENT_SCHEMA, naming_convention=NAMING_CONVENTION)
    # Load server defaults (timestamps) via RETURNING so rows are complete after commit.
    __mapper_args__ = {"eager_defaults": True}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


def check_in(column: str, values: Iterable[str]) -> str:
    """SQL for ``column IN ('A','B')`` from an enum, so CHECKs never drift from code."""
    return f"{column} IN ({', '.join(repr(str(v)) for v in values)})"
