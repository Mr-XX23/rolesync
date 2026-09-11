from __future__ import annotations

from collections.abc import Collection
from uuid import UUID

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
    ) -> AgentSession:
        row = AgentSession(tenant_id=tenant_id, user_id=user_id, mode=mode, goal_id=goal_id, status=status)
        async with self._sm.begin() as db:
            db.add(row)
        return row

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
    ) -> AgentSession | None:
        """Compare-and-set the status. Returns ``None`` if the session was not in ``expected``."""
        values: dict[str, object] = {"status": to}
        if to in _TERMINAL:
            values["ended_at"] = func.now()
        elif to is SessionStatus.RUNNING:
            values["ended_at"] = None
        if checkpoint_ref is not None:
            values["checkpoint_ref"] = checkpoint_ref

        stmt = update(AgentSession).where(AgentSession.id == session_id)
        if expected is not None:
            stmt = stmt.where(AgentSession.status.in_(list(expected)))
        stmt = stmt.values(**values).returning(AgentSession)
        async with self._sm.begin() as db:
            return (await db.scalars(stmt)).one_or_none()
