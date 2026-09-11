"""The "what happened" ledger: ``agent.audit`` + ``agent.saga_step``.

The two tables are written together when a write finishes, in one transaction, so a
crash can never leave an executed side effect audited but not in the saga log (or the
reverse).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.enums import SagaStatus, ToolOutcome
from app.db.models import AgentSession, AuditEntry, SagaStep


@dataclass(frozen=True, slots=True)
class AuditFields:
    tenant_id: UUID
    session_id: UUID
    user_id: UUID
    agent: str
    tool: str
    args: dict[str, Any]
    outcome: ToolOutcome
    result_summary: str | None = None
    result: Any | None = None
    idempotency_key: str | None = None
    pending_action_id: UUID | None = None
    duration_ms: int | None = None


class LedgerRepository:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sm = sessionmaker

    # --- audit -----------------------------------------------------------
    async def record(self, fields: AuditFields) -> AuditEntry:
        row = _audit_row(fields)
        async with self._sm.begin() as db:
            db.add(row)
        return row

    async def find_executed(self, *, tenant_id: UUID, idempotency_key: str) -> AuditEntry | None:
        async with self._sm() as db:
            return await db.scalar(
                select(AuditEntry).where(
                    AuditEntry.tenant_id == tenant_id,
                    AuditEntry.idempotency_key == idempotency_key,
                    AuditEntry.outcome == ToolOutcome.EXECUTED,
                )
            )

    async def list_audit(self, *, tenant_id: UUID, session_id: UUID) -> list[AuditEntry]:
        async with self._sm() as db:
            rows = await db.scalars(
                select(AuditEntry)
                .where(AuditEntry.tenant_id == tenant_id, AuditEntry.session_id == session_id)
                .order_by(AuditEntry.at)
            )
            return list(rows.all())

    # --- saga ------------------------------------------------------------
    async def begin_step(
        self,
        *,
        tenant_id: UUID,
        session_id: UUID,
        action: str,
        undo_action: dict[str, Any] | None,
        idempotency_key: str,
    ) -> tuple[SagaStep, bool]:
        """Record a PENDING step before the side effect runs (or return the existing one)."""
        async with self._sm.begin() as db:
            existing = await db.scalar(
                select(SagaStep).where(SagaStep.tenant_id == tenant_id, SagaStep.idempotency_key == idempotency_key)
            )
            if existing is not None:
                return existing, False
            # Serialize step numbering per session.
            await db.execute(select(AgentSession.id).where(AgentSession.id == session_id).with_for_update())
            last = await db.scalar(
                select(func.coalesce(func.max(SagaStep.step_no), 0)).where(SagaStep.session_id == session_id)
            )
            step = SagaStep(
                tenant_id=tenant_id,
                session_id=session_id,
                step_no=int(last) + 1,
                action=action,
                undo_action=undo_action,
                status=SagaStatus.PENDING,
                idempotency_key=idempotency_key,
            )
            db.add(step)
        return step, True

    async def complete_write(self, fields: AuditFields, *, step_id: UUID, ref_id: str | None) -> AuditEntry:
        row = _audit_row(fields)
        async with self._sm.begin() as db:
            db.add(row)
            await db.execute(
                update(SagaStep).where(SagaStep.id == step_id).values(status=SagaStatus.DONE, ref_id=ref_id)
            )
        return row

    async def fail_write(self, fields: AuditFields, *, step_id: UUID, error: str) -> AuditEntry:
        row = _audit_row(fields)
        async with self._sm.begin() as db:
            db.add(row)
            await db.execute(
                update(SagaStep).where(SagaStep.id == step_id).values(status=SagaStatus.FAILED, error=error)
            )
        return row

    async def list_steps(self, *, tenant_id: UUID, session_id: UUID) -> list[SagaStep]:
        async with self._sm() as db:
            rows = await db.scalars(
                select(SagaStep)
                .where(SagaStep.tenant_id == tenant_id, SagaStep.session_id == session_id)
                .order_by(SagaStep.step_no)
            )
            return list(rows.all())


def _audit_row(fields: AuditFields) -> AuditEntry:
    return AuditEntry(
        tenant_id=fields.tenant_id,
        session_id=fields.session_id,
        user_id=fields.user_id,
        agent=fields.agent,
        tool=fields.tool,
        args=fields.args,
        outcome=fields.outcome,
        result_summary=fields.result_summary,
        result=fields.result,
        idempotency_key=fields.idempotency_key,
        pending_action_id=fields.pending_action_id,
        duration_ms=fields.duration_ms,
    )
