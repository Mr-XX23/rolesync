"""session.turn and saga_step.turn: which request a completed action belongs to.

When an action fails, the actions the same request already completed are the ones the
rep is offered to undo; actions from earlier requests are left alone.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-12 12:00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('session', sa.Column('turn', sa.Integer(), server_default='0', nullable=False), schema='agent')
    op.add_column('saga_step', sa.Column('turn', sa.Integer(), nullable=True), schema='agent')
    op.create_index(
        op.f('ix_saga_step_session_id_turn'), 'saga_step', ['session_id', 'turn'], unique=False, schema='agent'
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_saga_step_session_id_turn'), table_name='saga_step', schema='agent')
    op.drop_column('saga_step', 'turn', schema='agent')
    op.drop_column('session', 'turn', schema='agent')
