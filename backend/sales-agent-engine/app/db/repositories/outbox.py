from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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


Deliver = Callable[[WorkspaceOutbox], Awaitable[Delivery]]


def _backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(300, 2 ** min(attempts, 9)))


class OutboxRepository:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sm = sessionmaker

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
        async with self._sm() as db:
            rows = await db.scalars(
                select(WorkspaceOutbox.session_id)
                .where(WorkspaceOutbox.status == OutboxStatus.PENDING, WorkspaceOutbox.next_attempt_at <= func.now())
                .group_by(WorkspaceOutbox.session_id)
                .order_by(func.min(WorkspaceOutbox.seq))
                .limit(limit)
            )
            return list(rows.all())

    async def deliver_session(self, session_id: UUID, deliver: Deliver, *, max_attempts: int, batch: int = 50) -> int:
        """Deliver one session's pending records strictly in order.

        A session-scoped advisory lock keeps two workers from interleaving the same
        session. A record waiting out a retry backoff blocks the ones behind it, so a
        task never arrives before its context.
        """
        delivered = 0
        async with self._sm.begin() as db:
            locked = await db.scalar(select(func.pg_try_advisory_xact_lock(func.hashtext(str(session_id)))))
            if not locked:
                return 0
            items = list(
                (
                    await db.scalars(
                        select(WorkspaceOutbox)
                        .where(WorkspaceOutbox.session_id == session_id, WorkspaceOutbox.status == OutboxStatus.PENDING)
                        .order_by(WorkspaceOutbox.seq)
                        .limit(batch)
                    )
                ).all()
            )
            now = utcnow()
            for position, item in enumerate(items):
                if item.next_attempt_at > now:
                    break
                following = items[position + 1] if position + 1 < len(items) else None
                if following is not None and following.target_id == item.target_id:
                    # Superseded by the very next upsert of the same record. (Only adjacent ones:
                    # skipping an earlier context upsert could send its tasks before it exists.)
                    item.status = OutboxStatus.DELIVERED
                    item.delivered_at = now
                    continue
                outcome = await deliver(item)
                if outcome.result is DeliveryResult.DELIVERED:
                    item.status = OutboxStatus.DELIVERED
                    item.delivered_at = utcnow()
                    delivered += 1
                    continue
                item.attempts += 1
                item.last_error = outcome.detail
                if outcome.result is DeliveryResult.REJECTED or item.attempts >= max_attempts:
                    item.status = OutboxStatus.FAILED
                    continue
                item.next_attempt_at = utcnow() + _backoff(item.attempts)
                break
        return delivered

    async def list_for_session(self, session_id: UUID) -> list[WorkspaceOutbox]:
        async with self._sm() as db:
            rows = await db.scalars(
                select(WorkspaceOutbox).where(WorkspaceOutbox.session_id == session_id).order_by(WorkspaceOutbox.seq)
            )
            return list(rows.all())
