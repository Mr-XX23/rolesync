from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.enums import PendingActionStatus
from app.db.models import AgentSession, PendingAction


class PendingActionRepository:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sm = sessionmaker

    async def get_or_create(
        self,
        *,
        tenant_id: UUID,
        session_id: UUID,
        idempotency_key: str,
        agent: str,
        tool: str,
        args: dict[str, Any],
        preview: dict[str, Any],
        expires_at: datetime,
    ) -> tuple[PendingAction, bool]:
        """Insert a PENDING action, or return the one already recorded for this key.

        A graph node that resumes after an interrupt re-runs from the top, so the gate
        asks for the same approval again; this makes that a lookup, not a duplicate.
        """
        stmt = (
            insert(PendingAction)
            .values(
                tenant_id=tenant_id,
                session_id=session_id,
                idempotency_key=idempotency_key,
                agent=agent,
                tool=tool,
                args=args,
                preview=preview,
                status=PendingActionStatus.PENDING,
                expires_at=expires_at,
            )
            .on_conflict_do_nothing(constraint="uq_pending_action_tenant_key")
            .returning(PendingAction)
        )
        async with self._sm.begin() as db:
            created = (await db.scalars(stmt)).one_or_none()
            if created is not None:
                return created, True
            existing = await db.scalar(
                select(PendingAction).where(
                    PendingAction.tenant_id == tenant_id,
                    PendingAction.idempotency_key == idempotency_key,
                )
            )
            assert existing is not None  # conflict implies the row exists
            return existing, False

    async def get(self, *, tenant_id: UUID, action_id: UUID) -> PendingAction | None:
        async with self._sm() as db:
            return await db.scalar(
                select(PendingAction).where(PendingAction.id == action_id, PendingAction.tenant_id == tenant_id)
            )

    async def get_by_key(self, *, tenant_id: UUID, idempotency_key: str) -> PendingAction | None:
        async with self._sm() as db:
            return await db.scalar(
                select(PendingAction).where(
                    PendingAction.tenant_id == tenant_id,
                    PendingAction.idempotency_key == idempotency_key,
                )
            )

    async def resolve(
        self,
        *,
        tenant_id: UUID,
        action_id: UUID,
        status: PendingActionStatus,
        resolved_by: UUID | None,
        edited_args: dict[str, Any] | None = None,
        note: str | None = None,
    ) -> PendingAction | None:
        """Record the human decision. Only a still-PENDING, unexpired action can be resolved;
        ``None`` means another decision (or the TTL) got there first."""
        stmt = (
            update(PendingAction)
            .where(
                PendingAction.id == action_id,
                PendingAction.tenant_id == tenant_id,
                PendingAction.status == PendingActionStatus.PENDING,
                PendingAction.expires_at > func.now(),
            )
            .values(
                status=status,
                resolved_by=resolved_by,
                resolved_at=func.now(),
                edited_args=edited_args,
                decision_note=note,
            )
            .returning(PendingAction)
        )
        async with self._sm.begin() as db:
            return (await db.scalars(stmt)).one_or_none()

    async def expire_due(self, *, limit: int = 200) -> list[PendingAction]:
        """Mark PENDING actions whose TTL has passed as EXPIRED (across tenants: this is the
        maintenance worker). Returns the rows it expired; a concurrent decision wins the race."""
        due = (
            select(PendingAction.id)
            .where(PendingAction.status == PendingActionStatus.PENDING, PendingAction.expires_at <= func.now())
            .order_by(PendingAction.expires_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        stmt = (
            update(PendingAction)
            .where(PendingAction.id.in_(due.scalar_subquery()), PendingAction.status == PendingActionStatus.PENDING)
            .values(status=PendingActionStatus.EXPIRED, resolved_at=func.now())
            .returning(PendingAction)
        )
        async with self._sm.begin() as db:
            return list((await db.scalars(stmt)).all())

    async def latest_decision_if_settled(self, *, tenant_id: UUID, session_id: UUID) -> PendingAction | None:
        """The most recently decided action of a session, but only if none is still PENDING:
        a paused session in that state was decided and never resumed."""
        async with self._sm() as db:
            still_pending = await db.scalar(
                select(func.count())
                .select_from(PendingAction)
                .where(
                    PendingAction.tenant_id == tenant_id,
                    PendingAction.session_id == session_id,
                    PendingAction.status == PendingActionStatus.PENDING,
                )
            )
            if still_pending:
                return None
            return await db.scalar(
                select(PendingAction)
                .where(
                    PendingAction.tenant_id == tenant_id,
                    PendingAction.session_id == session_id,
                    PendingAction.resolved_at.is_not(None),
                )
                .order_by(PendingAction.resolved_at.desc())
                .limit(1)
            )

    async def list_for_user(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        status: PendingActionStatus | None = None,
        session_id: UUID | None = None,
        limit: int = 50,
    ) -> list[PendingAction]:
        stmt = (
            select(PendingAction)
            .join(AgentSession, AgentSession.id == PendingAction.session_id)
            .where(PendingAction.tenant_id == tenant_id, AgentSession.user_id == user_id)
            .order_by(PendingAction.created_at.desc())
            .limit(limit)
        )
        if status is not None:
            stmt = stmt.where(PendingAction.status == status)
        if session_id is not None:
            stmt = stmt.where(PendingAction.session_id == session_id)
        async with self._sm() as db:
            return list((await db.scalars(stmt)).all())
