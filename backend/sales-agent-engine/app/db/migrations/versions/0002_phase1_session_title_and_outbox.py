"""Phase 1: session.title and the workspace outbox (goals, tasks, notes live in workspace-service).

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-11 19:46:00.479801
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('workspace_outbox',
    sa.Column('seq', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('context_id', sa.Uuid(), nullable=False),
    sa.Column('target_id', sa.Uuid(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.Text(), server_default='PENDING', nullable=False),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('next_attempt_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("kind IN ('CONTEXT', 'TASK', 'NOTE')", name=op.f('ck_workspace_outbox_kind')),
    sa.CheckConstraint("status IN ('PENDING', 'DELIVERED', 'FAILED')", name=op.f('ck_workspace_outbox_status')),
    sa.PrimaryKeyConstraint('seq', name=op.f('pk_workspace_outbox')),
    schema='agent'
    )
    op.create_index('ix_workspace_outbox_due', 'workspace_outbox', ['next_attempt_at'], unique=False, schema='agent', postgresql_where=sa.text("status = 'PENDING'"))
    op.create_index('ix_workspace_outbox_session_seq', 'workspace_outbox', ['session_id', 'seq'], unique=False, schema='agent')
    op.add_column('session', sa.Column('title', sa.Text(), nullable=True), schema='agent')


def downgrade() -> None:
    op.drop_column('session', 'title', schema='agent')
    op.drop_index('ix_workspace_outbox_session_seq', table_name='workspace_outbox', schema='agent')
    op.drop_index('ix_workspace_outbox_due', table_name='workspace_outbox', schema='agent', postgresql_where=sa.text("status = 'PENDING'"))
    op.drop_table('workspace_outbox', schema='agent')
