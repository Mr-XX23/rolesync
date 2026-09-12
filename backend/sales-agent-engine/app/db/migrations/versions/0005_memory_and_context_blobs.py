"""agent.memory (versioned shared memory) and agent.context_blob (offloaded tool results).

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-12 18:00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0005'
down_revision: str | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('memory',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('scope', sa.Text(), nullable=False),
    sa.Column('scope_key', sa.Text(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('content', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('written_by', sa.Uuid(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("scope IN ('CONVERSATION', 'REP', 'DEAL', 'ACCOUNT')", name=op.f('ck_memory_scope')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_memory')),
    sa.UniqueConstraint('tenant_id', 'scope', 'scope_key', 'version', name='uq_memory_tenant_scope_key_version'),
    schema='agent'
    )
    op.create_index('ix_memory_tenant_scope_updated', 'memory', ['tenant_id', 'scope', 'updated_at'], unique=False, schema='agent')
    op.create_table('context_blob',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('call_id', sa.Text(), nullable=False),
    sa.Column('tool', sa.Text(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('chars', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['agent.session.id'], name=op.f('fk_context_blob_session_id_session'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_context_blob')),
    sa.UniqueConstraint('session_id', 'call_id', name='uq_context_blob_session_call'),
    schema='agent'
    )


def downgrade() -> None:
    op.drop_table('context_blob', schema='agent')
    op.drop_index('ix_memory_tenant_scope_updated', table_name='memory', schema='agent')
    op.drop_table('memory', schema='agent')
