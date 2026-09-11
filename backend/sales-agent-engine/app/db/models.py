"""SQLAlchemy models for schema ``agent`` (implementation-plan §3).

Every table carries ``tenant_id``; repositories always filter on it using the
server-side ``AgentContext``/``TenantContext``, never on client input.

Deliberate additions to the plan's column lists (each needed for correctness):
- ``pending_action``: ``agent``, ``idempotency_key`` (a resumed graph node re-runs
  the gate, which must find the same approval instead of creating another),
  ``edited_args`` (the original ``args`` stay intact for audit), ``decision_note``.
- ``audit``: ``user_id``, ``outcome`` (denials/rejections are audited too),
  ``idempotency_key`` + ``result`` (an already-executed write returns its prior
  result instead of running twice), ``pending_action_id``, ``duration_ms``.
- ``saga_step``: ``PENDING`` status (the step is recorded before the side effect),
  ``idempotency_key``, ``error``.
- ``session.title``: the first prompt, for session lists.
- ``workspace_outbox``: goals, tasks and notes live in workspace-service; the engine
  records them here first and a worker delivers them, so the agent never waits on (or
  fails because of) that service.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.context import RunMode
from app.core.enums import PendingActionStatus, SagaStatus, SessionStatus, ToolOutcome
from app.db.base import Base, TimestampMixin, check_in


class AgentSession(TimestampMixin, Base):
    """One interactive conversation or one autonomous wake."""

    __tablename__ = "session"
    __table_args__ = (
        CheckConstraint(check_in("mode", RunMode), name="mode"),
        CheckConstraint(check_in("status", SessionStatus), name="status"),
        Index("ix_session_tenant_user_started", "tenant_id", "user_id", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    goal_id: Mapped[uuid.UUID | None] = mapped_column()
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    checkpoint_ref: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PendingAction(TimestampMixin, Base):
    """The human-in-the-loop queue: a write waiting for approve / edit / reject."""

    __tablename__ = "pending_action"
    __table_args__ = (
        CheckConstraint(check_in("status", PendingActionStatus), name="status"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_pending_action_tenant_key"),
        Index("ix_pending_action_tenant_status", "tenant_id", "status"),
        Index("ix_pending_action_session", "session_id"),
        Index("ix_pending_action_due", "expires_at", postgresql_where=text("status = 'PENDING'")),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent.session.id", ondelete="CASCADE"), nullable=False)
    agent: Mapped[str] = mapped_column(Text, nullable=False)
    tool: Mapped[str] = mapped_column(Text, nullable=False)
    args: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    preview: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    edited_args: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    decision_note: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEntry(Base):
    """Append-only record of every gated tool call (compliance, not debugging)."""

    __tablename__ = "audit"
    __table_args__ = (
        CheckConstraint(check_in("outcome", ToolOutcome), name="outcome"),
        Index("ix_audit_tenant_session_at", "tenant_id", "session_id", "at"),
        # At most one successful execution per idempotency key.
        Index(
            "uq_audit_executed_key",
            "tenant_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("outcome = 'EXECUTED' AND idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    session_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    agent: Mapped[str] = mapped_column(Text, nullable=False)
    tool: Mapped[str] = mapped_column(Text, nullable=False)
    args: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    result_summary: Mapped[str | None] = mapped_column(Text)
    result: Mapped[Any | None] = mapped_column(JSONB)
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    pending_action_id: Mapped[uuid.UUID | None] = mapped_column()
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SagaStep(TimestampMixin, Base):
    """Side-effect log used to compensate (undo) on mid-plan failure."""

    __tablename__ = "saga_step"
    __table_args__ = (
        CheckConstraint(check_in("status", SagaStatus), name="status"),
        UniqueConstraint("session_id", "step_no", name="uq_saga_step_session_step"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_saga_step_tenant_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent.session.id", ondelete="CASCADE"), nullable=False)
    step_no: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    undo_action: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    ref_id: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)


class OutboxKind(StrEnum):
    CONTEXT = "CONTEXT"
    TASK = "TASK"
    NOTE = "NOTE"


class OutboxStatus(StrEnum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


class WorkspaceOutbox(Base):
    """Workspace records waiting to be delivered to workspace-service, in order per session.

    Every record is an idempotent upsert keyed by ``target_id`` (a deterministic UUID),
    so redelivery after a timeout or crash is harmless.
    """

    __tablename__ = "workspace_outbox"
    __table_args__ = (
        CheckConstraint(check_in("kind", OutboxKind), name="kind"),
        CheckConstraint(check_in("status", OutboxStatus), name="status"),
        Index("ix_workspace_outbox_due", "next_attempt_at", postgresql_where=text("status = 'PENDING'")),
        Index("ix_workspace_outbox_session_seq", "session_id", "seq"),
    )

    seq: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    session_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    context_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=OutboxStatus.PENDING.value)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
