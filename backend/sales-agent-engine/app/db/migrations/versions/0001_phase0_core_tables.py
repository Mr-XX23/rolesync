"""Phase 0 core tables: session, pending_action, audit, saga_step.

Revision ID: 0001
Revises: 
Create Date: 2026-09-11 16:17:37.773243
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('audit',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('agent', sa.Text(), nullable=False),
    sa.Column('tool', sa.Text(), nullable=False),
    sa.Column('args', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('outcome', sa.Text(), nullable=False),
    sa.Column('result_summary', sa.Text(), nullable=True),
    sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('idempotency_key', sa.Text(), nullable=True),
    sa.Column('pending_action_id', sa.Uuid(), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("outcome IN ('EXECUTED', 'FAILED', 'DENIED', 'INVALID', 'REJECTED', 'EXPIRED')", name=op.f('ck_audit_outcome')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit')),
    schema='agent'
    )
    op.create_index('ix_audit_tenant_session_at', 'audit', ['tenant_id', 'session_id', 'at'], unique=False, schema='agent')
    op.create_index('uq_audit_executed_key', 'audit', ['tenant_id', 'idempotency_key'], unique=True, schema='agent', postgresql_where=sa.text("outcome = 'EXECUTED' AND idempotency_key IS NOT NULL"))
    op.create_table('session',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('goal_id', sa.Uuid(), nullable=True),
    sa.Column('mode', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('checkpoint_ref', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("mode IN ('INTERACTIVE', 'AUTONOMOUS')", name=op.f('ck_session_mode')),
    sa.CheckConstraint("status IN ('RUNNING', 'AWAITING_APPROVAL', 'DONE', 'FAILED', 'HALTED')", name=op.f('ck_session_status')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_session')),
    schema='agent'
    )
    op.create_index('ix_session_tenant_user_started', 'session', ['tenant_id', 'user_id', 'started_at'], unique=False, schema='agent')
    op.create_table('pending_action',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('agent', sa.Text(), nullable=False),
    sa.Column('tool', sa.Text(), nullable=False),
    sa.Column('args', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('preview', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('idempotency_key', sa.Text(), nullable=False),
    sa.Column('edited_args', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('decision_note', sa.Text(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('resolved_by', sa.Uuid(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('PENDING', 'APPROVED', 'EDITED', 'REJECTED', 'EXPIRED')", name=op.f('ck_pending_action_status')),
    sa.ForeignKeyConstraint(['session_id'], ['agent.session.id'], name=op.f('fk_pending_action_session_id_session'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pending_action')),
    sa.UniqueConstraint('tenant_id', 'idempotency_key', name='uq_pending_action_tenant_key'),
    schema='agent'
    )
    op.create_index('ix_pending_action_due', 'pending_action', ['expires_at'], unique=False, schema='agent', postgresql_where=sa.text("status = 'PENDING'"))
    op.create_index('ix_pending_action_session', 'pending_action', ['session_id'], unique=False, schema='agent')
    op.create_index('ix_pending_action_tenant_status', 'pending_action', ['tenant_id', 'status'], unique=False, schema='agent')
    op.create_table('saga_step',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('step_no', sa.Integer(), nullable=False),
    sa.Column('action', sa.Text(), nullable=False),
    sa.Column('undo_action', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('ref_id', sa.Text(), nullable=True),
    sa.Column('idempotency_key', sa.Text(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('PENDING', 'DONE', 'FAILED', 'COMPENSATED', 'COMPENSATION_FAILED')", name=op.f('ck_saga_step_status')),
    sa.ForeignKeyConstraint(['session_id'], ['agent.session.id'], name=op.f('fk_saga_step_session_id_session'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_saga_step')),
    sa.UniqueConstraint('session_id', 'step_no', name='uq_saga_step_session_step'),
    sa.UniqueConstraint('tenant_id', 'idempotency_key', name='uq_saga_step_tenant_key'),
    schema='agent'
    )


def downgrade() -> None:
    op.drop_table('saga_step', schema='agent')
    op.drop_index('ix_pending_action_tenant_status', table_name='pending_action', schema='agent')
    op.drop_index('ix_pending_action_session', table_name='pending_action', schema='agent')
    op.drop_index('ix_pending_action_due', table_name='pending_action', schema='agent', postgresql_where=sa.text("status = 'PENDING'"))
    op.drop_table('pending_action', schema='agent')
    op.drop_index('ix_session_tenant_user_started', table_name='session', schema='agent')
    op.drop_table('session', schema='agent')
    op.drop_index('uq_audit_executed_key', table_name='audit', schema='agent', postgresql_where=sa.text("outcome = 'EXECUTED' AND idempotency_key IS NOT NULL"))
    op.drop_index('ix_audit_tenant_session_at', table_name='audit', schema='agent')
    op.drop_table('audit', schema='agent')
