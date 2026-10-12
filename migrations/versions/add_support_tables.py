# migrations/versions/add_support_tables.py
"""add support tables
Revision ID: d1e2f3a4b5c6
Revises: c2d3e4f5a6b7
Create Date: 2026-10-12 10:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'd1e2f3a4b5c6'
down_revision = 'c2d3e4f5a6b7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # === Таблица support_tickets ===
    op.create_table(
        'support_tickets',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('category', sa.String(length=16), nullable=False),
        sa.Column('subject', sa.String(length=200), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='open'),
        sa.Column('last_user_message_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_admin_message_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('user_last_viewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('admin_last_viewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_support_tickets_user_status', 'support_tickets', ['user_id', 'status'], unique=False)
    op.create_index(
        'ix_support_tickets_admin_queue',
        'support_tickets',
        ['status', 'last_user_message_at'],
        unique=False,
        postgresql_where=sa.text("status IN ('open', 'in_progress')"),
    )
    op.create_index('ix_support_tickets_created', 'support_tickets', ['created_at'], unique=False)

    # === Таблица support_messages ===
    op.create_table(
        'support_messages',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('ticket_id', sa.BigInteger(), nullable=False),
        sa.Column('author_id', sa.BigInteger(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_by_admin_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['ticket_id'], ['support_tickets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['deleted_by_admin_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_support_messages_ticket', 'support_messages', ['ticket_id', 'created_at'], unique=False)
    op.create_index(
        'ix_support_messages_active',
        'support_messages',
        ['ticket_id', 'created_at'],
        unique=False,
        postgresql_where=sa.text('is_deleted = false'),
    )


def downgrade() -> None:
    op.drop_index('ix_support_messages_active', table_name='support_messages', postgresql_where=sa.text('is_deleted = false'))
    op.drop_index('ix_support_messages_ticket', table_name='support_messages')
    op.drop_table('support_messages')
    op.drop_index('ix_support_tickets_created', table_name='support_tickets')
    op.drop_index('ix_support_tickets_admin_queue', table_name='support_tickets', postgresql_where=sa.text("status IN ('open', 'in_progress')"))
    op.drop_index('ix_support_tickets_user_status', table_name='support_tickets')
    op.drop_table('support_tickets')