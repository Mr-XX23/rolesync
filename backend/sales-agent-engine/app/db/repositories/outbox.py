from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.clock import utcnow
from app.db.models import OutboxKind, OutboxStatus, WorkspaceOutbox
from app.platform.workspace_client import Delivery, DeliveryResult


@dataclass(frozen=True, slots=True)
class OutboxItem:
    tenant_id: UUID
    session_id: UUID
    user_id: UUID
    kind: OutboxKind
    context_id: UUID
    target_id: UUID
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class OutboxRecord:
    seq: int
    tenant_id: UUID
    session_id: UUID
    user_id: UUID
    kind: str
    context_id: UUID
    target_id: UUID
    payload: dict[str, Any]
    attempts: int
    next_attempt_at: datetime


Deliver = Callable[[OutboxRecord], Awaitable[Delivery]]

# A task or note whose context is missing only waits a little for it: the context is always
# enqueued first, so a lasting 404 means the context was rejected and waiting would only
# block the session's later records.
MAX_NOT_FOUND_ATTEMPTS = 4


def _backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(300, 2 ** min(attempts, 9)))


class OutboxRepository:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], engine: AsyncEngine) -> None:
        self._sm = sessionmaker
        self._engine = engine

    async def enqueue(self, items: Sequence[OutboxItem]) -> None:
        if not items:
            return
        async with self._sm.begin() as db:
            db.add_all(
                WorkspaceOutbox(
                    tenant_id=item.tenant_id,
                    session_id=item.session_id,
                    user_id=item.user_id,
                    kind=item.kind,
                    context_id=item.context_id,
                    target_id=item.target_id,
                    payload=item.payload,
                    status=OutboxStatus.PENDING,
                )
                for item in items
            )

    async def due_sessions(self, limit: int = 50) -> list[UUID]:
        """Sessions whose *first* pending record is due. A session waiting out a retry backoff
        on its head record is skipped, so it can't crowd out sessions that can make progress."""
        head = (
            select(WorkspaceOutbox.session_id, func.min(WorkspaceOutbox.seq).label("head_seq"))
            .where(WorkspaceOutbox.status == OutboxStatus.PENDING)
            .group_by(WorkspaceOutbox.session_id)
            .subquery()
        )
        stmt = (
            select(WorkspaceOutbox.session_id)
            .join(head, WorkspaceOutbox.seq == head.c.head_seq)
            .where(WorkspaceOutbox.next_attempt_at <= func.now())
            .order_by(WorkspaceOutbox.seq)
            .limit(limit)
        )
        async with self._sm() as db:
            return list((await db.scalars(stmt)).all())

    async def deliver_session(
        self, session_id: UUID, deliver: Deliver, *, max_attempts: int, batch: int = 20
    ) -> int:
        """Deliver one session's pending records strictly in order.

        A session-level advisory lock keeps two workers from interleaving one session. Each
        record's outcome is committed on its own, and no transaction stays open across the
        HTTP calls. A record waiting out a backoff blocks the ones behind it, so a task never
        arrives before its context.
        """
        delivered = 0
        lock_key = func.hashtext(str(session_id))
        async with self._engine.connect() as conn:
            locked = await conn.scalar(select(func.pg_try_advisory_lock(lock_key)))
            await conn.commit()
            if not locked:
                return 0
            try:
                rows = (
                    await conn.execute(
                        select(WorkspaceOutbox.__table__)
                        .where(WorkspaceOutbox.session_id == session_id, WorkspaceOutbox.status == OutboxStatus.PENDING)
                        .order_by(WorkspaceOutbox.seq)
                        .limit(batch)
                    )
                ).all()
                await conn.commit()
                items = [
                    OutboxRecord(
                        seq=row.seq, tenant_id=row.tenant_id, session_id=row.session_id, user_id=row.user_id,
                        kind=row.kind, context_id=row.context_id, target_id=row.target_id, payload=row.payload,
                        attempts=row.attempts, next_attempt_at=row.next_attempt_at,
                    )
                    for row in rows
                ]
                for position, item in enumerate(items):
                    if item.next_attempt_at > utcnow():
                        break
                    following = items[position + 1] if position + 1 < len(items) else None
                    if following is not None and following.target_id == item.target_id:
                        # Superseded by the very next upsert of the same record. (Only adjacent ones:
                        # skipping an earlier context upsert could send its tasks before it exists.)
                        await self._set(conn, item.seq, status=OutboxStatus.DELIVERED, delivered_at=utcnow())
                        continue
                    outcome = await deliver(item)
                    if outcome.result is DeliveryResult.DELIVERED:
                        await self._set(conn, item.seq, status=OutboxStatus.DELIVERED, delivered_at=utcnow())
                        delivered += 1
                        continue
                    attempts = item.attempts + 1
                    limit = MAX_NOT_FOUND_ATTEMPTS if outcome.not_found else max_attempts
                    if outcome.result is DeliveryResult.REJECTED or attempts >= limit:
                        await self._set(
                            conn, item.seq, status=OutboxStatus.FAILED, attempts=attempts, last_error=outcome.detail
                        )
                        continue
                    await self._set(
                        conn, item.seq, attempts=attempts, last_error=outcome.detail,
                        next_attempt_at=utcnow() + _backoff(attempts),
                    )
                    break
            finally:
                try:
                    await conn.execute(select(func.pg_advisory_unlock(lock_key)))
                    await conn.commit()
                except Exception:
                    # A session-level lock outlives the transaction: drop the connection so it
                    # can't stay locked inside the pool.
                    await conn.invalidate()
                    raise
        return delivered

    @staticmethod
    async def _set(conn: Any, seq: int, **values: Any) -> None:
        await conn.execute(update(WorkspaceOutbox.__table__).where(WorkspaceOutbox.seq == seq).values(**values))
        await conn.commit()

    async def list_for_session(self, session_id: UUID) -> list[WorkspaceOutbox]:
        async with self._sm() as db:
            rows = await db.scalars(
                select(WorkspaceOutbox).where(WorkspaceOutbox.session_id == session_id).order_by(WorkspaceOutbox.seq)
            )
            return list(rows.all())
