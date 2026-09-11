"""UNKNOWN tool outcome; session.settled_event_id.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-12 09:00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WITH_UNKNOWN = "outcome IN ('EXECUTED', 'FAILED', 'UNKNOWN', 'DENIED', 'INVALID', 'REJECTED', 'EXPIRED')"
_WITHOUT_UNKNOWN = "outcome IN ('EXECUTED', 'FAILED', 'DENIED', 'INVALID', 'REJECTED', 'EXPIRED')"


def upgrade() -> None:
    op.drop_constraint(op.f('ck_audit_outcome'), 'audit', schema='agent', type_='check')
    op.create_check_constraint(op.f('ck_audit_outcome'), 'audit', _WITH_UNKNOWN, schema='agent')
    op.add_column('session', sa.Column('settled_event_id', sa.Text(), nullable=True), schema='agent')


def downgrade() -> None:
    op.drop_column('session', 'settled_event_id', schema='agent')
    op.execute("UPDATE agent.audit SET outcome = 'FAILED' WHERE outcome = 'UNKNOWN'")
    op.drop_constraint(op.f('ck_audit_outcome'), 'audit', schema='agent', type_='check')
    op.create_check_constraint(op.f('ck_audit_outcome'), 'audit', _WITHOUT_UNKNOWN, schema='agent')
