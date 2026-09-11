from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.context import RunMode
from app.core.enums import SessionStatus
from app.db.models import AgentSession

_TERMINAL = {SessionStatus.DONE, SessionStatus.FAILED, SessionStatus.HALTED}


class SessionRepository:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sm = sessionmaker

    async def create(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        mode: RunMode,
        goal_id: UUID | None = None,
        status: SessionStatus = SessionStatus.RUNNING,
        title: str | None = None,
        session_id: UUID | None = None,
    ) -> AgentSession:
        row = AgentSession(
            id=session_id or uuid4(), tenant_id=tenant_id, user_id=user_id, mode=mode, goal_id=goal_id, status=status,
            title=title,
        )
        async with self._sm.begin() as db:
            db.add(row)
        return row

    async def list_for_user(self, *, tenant_id: UUID, user_id: UUID, limit: int = 50) -> list[AgentSession]:
        async with self._sm() as db:
            rows = await db.scalars(
                select(AgentSession)
                .where(AgentSession.tenant_id == tenant_id, AgentSession.user_id == user_id)
                .order_by(AgentSession.started_at.desc())
                .limit(limit)
            )
            return list(rows.all())

    async def list_by_status(
        self, status: SessionStatus, *, updated_before: datetime | None = None, limit: int = 500
    ) -> list[AgentSession]:
        stmt = select(AgentSession).where(AgentSession.status == status)
        if updated_before is not None:
            stmt = stmt.where(AgentSession.updated_at < updated_before)
        async with self._sm() as db:
            rows = await db.scalars(stmt.order_by(AgentSession.updated_at).limit(limit))
            return list(rows.all())

    async def count_running(self, tenant_id: UUID) -> int:
        async with self._sm() as db:
            return int(
                await db.scalar(
                    select(func.count())
                    .select_from(AgentSession)
                    .where(AgentSession.tenant_id == tenant_id, AgentSession.status == SessionStatus.RUNNING)
                )
                or 0
            )

    async def get(self, session_id: UUID) -> AgentSession | None:
        async with self._sm() as db:
            return await db.get(AgentSession, session_id)

    async def get_owned(self, *, tenant_id: UUID, user_id: UUID, session_id: UUID) -> AgentSession | None:
        async with self._sm() as db:
            return await db.scalar(
                select(AgentSession).where(
                    AgentSession.id == session_id,
                    AgentSession.tenant_id == tenant_id,
                    AgentSession.user_id == user_id,
                )
            )

    async def transition(
        self,
        session_id: UUID,
        *,
        to: SessionStatus,
        expected: Collection[SessionStatus] | None = None,
        checkpoint_ref: str | None = None,
        settled_event_id: str | None = None,
    ) -> AgentSession | None:
        """Compare-and-set the status. Returns ``None`` if the session was not in ``expected``."""
        values: dict[str, object] = {"status": to}
        if to in _TERMINAL:
            values["ended_at"] = func.now()
        elif to is SessionStatus.RUNNING:
            values["ended_at"] = None
        if checkpoint_ref is not None:
            values["checkpoint_ref"] = checkpoint_ref
        if settled_event_id is not None:
            values["settled_event_id"] = settled_event_id

        stmt = update(AgentSession).where(AgentSession.id == session_id)
        if expected is not None:
            stmt = stmt.where(AgentSession.status.in_(list(expected)))
        stmt = stmt.values(**values).returning(AgentSession)
        async with self._sm.begin() as db:
            return (await db.scalars(stmt)).one_or_none()
