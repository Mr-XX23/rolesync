"""The "what happened" ledger: ``agent.audit`` + ``agent.saga_step``.

The two tables are written together when a write finishes, in one transaction, so a
crash can never leave an executed side effect audited but not in the saga log (or the
reverse). Compensation (undoing a completed step) is written the same way.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, select, update
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


@dataclass(frozen=True, slots=True)
class StepRecord:
    """A saga step with the summary its execution was audited with."""

    step: SagaStep
    summary: str | None


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
        idempotency_key: str,
        undo_action: dict[str, Any] | None = None,
        turn: int | None = None,
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
                turn=turn,
                step_no=int(last) + 1,
                action=action,
                undo_action=undo_action,
                status=SagaStatus.PENDING,
                idempotency_key=idempotency_key,
            )
            db.add(step)
        return step, True

    async def complete_write(
        self,
        fields: AuditFields,
        *,
        step_id: UUID,
        ref_id: str | None,
        undo_action: dict[str, Any] | None = None,
    ) -> AuditEntry:
        row = _audit_row(fields)
        values: dict[str, Any] = {"status": SagaStatus.DONE, "ref_id": ref_id}
        if undo_action is not None:
            values["undo_action"] = undo_action
        async with self._sm.begin() as db:
            db.add(row)
            await db.execute(update(SagaStep).where(SagaStep.id == step_id).values(**values))
        return row

    async def fail_write(self, fields: AuditFields, *, step_id: UUID, error: str) -> AuditEntry:
        row = _audit_row(fields)
        async with self._sm.begin() as db:
            db.add(row)
            await db.execute(
                update(SagaStep).where(SagaStep.id == step_id).values(status=SagaStatus.FAILED, error=error)
            )
        return row

    async def finish_compensation(
        self, fields: AuditFields, *, step_id: UUID, compensated: bool, error: str | None = None
    ) -> bool:
        """Record an undo attempt on a DONE step. ``False`` if the step was no longer DONE
        (another undo got there first); nothing is written then."""
        status = SagaStatus.COMPENSATED if compensated else SagaStatus.COMPENSATION_FAILED
        async with self._sm.begin() as db:
            updated = await db.scalar(
                update(SagaStep)
                .where(SagaStep.id == step_id, SagaStep.status == SagaStatus.DONE)
                .values(status=status, error=error)
                .returning(SagaStep.id)
            )
            if updated is None:
                return False
            db.add(_audit_row(fields))
        return True

    async def find_step(self, *, tenant_id: UUID, idempotency_key: str) -> SagaStep | None:
        async with self._sm() as db:
            return await db.scalar(
                select(SagaStep).where(SagaStep.tenant_id == tenant_id, SagaStep.idempotency_key == idempotency_key)
            )

    async def list_steps(self, *, tenant_id: UUID, session_id: UUID) -> list[SagaStep]:
        async with self._sm() as db:
            rows = await db.scalars(
                select(SagaStep)
                .where(SagaStep.tenant_id == tenant_id, SagaStep.session_id == session_id)
                .order_by(SagaStep.step_no)
            )
            return list(rows.all())

    async def undoable_steps(self, *, tenant_id: UUID, session_id: UUID, turn: int) -> list[SagaStep]:
        """Completed steps of one request that know how to reverse themselves, oldest first."""
        async with self._sm() as db:
            rows = await db.scalars(
                select(SagaStep)
                .where(
                    SagaStep.tenant_id == tenant_id,
                    SagaStep.session_id == session_id,
                    SagaStep.turn == turn,
                    SagaStep.status == SagaStatus.DONE,
                    SagaStep.undo_action.is_not(None),
                )
                .order_by(SagaStep.step_no)
            )
            return list(rows.all())

    async def step_records(
        self,
        *,
        tenant_id: UUID,
        session_id: UUID,
        step_ids: Collection[UUID] | None = None,
        turns: Collection[int] | None = None,
    ) -> list[StepRecord]:
        """A session's steps (by id and/or request) with their audited summaries, oldest first."""
        stmt = (
            select(SagaStep, AuditEntry.result_summary)
            .outerjoin(
                AuditEntry,
                and_(
                    AuditEntry.tenant_id == SagaStep.tenant_id,
                    AuditEntry.idempotency_key == SagaStep.idempotency_key,
                    AuditEntry.outcome == ToolOutcome.EXECUTED,
                ),
            )
            .where(SagaStep.tenant_id == tenant_id, SagaStep.session_id == session_id)
            .order_by(SagaStep.step_no)
        )
        if step_ids is not None:
            stmt = stmt.where(SagaStep.id.in_(list(step_ids)))
        if turns is not None:
            stmt = stmt.where(SagaStep.turn.in_(list(turns)))
        async with self._sm() as db:
            return [StepRecord(step=step, summary=summary) for step, summary in (await db.execute(stmt)).all()]


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
