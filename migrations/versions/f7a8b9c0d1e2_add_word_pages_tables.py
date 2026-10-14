"""add word pages tables

Revision ID: f7a8b9c0d1e2
Revises: d1e2f3a4b5c6
Create Date: 2026-10-14 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'f7a8b9c0d1e2'
down_revision = 'd1e2f3a4b5c6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # === Таблица word_pages ===
    op.create_table(
        'word_pages',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('word_id', sa.BigInteger(), nullable=False),
        sa.Column('slug', sa.String(length=128), nullable=False),
        sa.Column('content', postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column('meta_title', sa.String(length=200), nullable=True),
        sa.Column('meta_description', sa.String(length=300), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='draft'),
        sa.Column('view_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('gen_prompt_tokens', sa.Integer(), nullable=True),
        sa.Column('gen_completion_tokens', sa.Integer(), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['word_id'], ['words.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('word_id', name='uq_word_pages_word_id'),
        sa.UniqueConstraint('slug', name='uq_word_pages_slug'),
    )
    op.create_index('ix_word_pages_slug', 'word_pages', ['slug'], unique=False)
    op.create_index('ix_word_pages_status', 'word_pages', ['status'], unique=False)
    op.create_index('ix_word_pages_status_published', 'word_pages', ['status', 'published_at'], unique=False)

    # === Таблица word_page_queue ===
    op.create_table(
        'word_page_queue',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('word_id', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='queued'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('attempt_count', sa.SmallInteger(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['word_id'], ['words.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('word_id', name='uq_word_page_queue_word_id'),
    )
    op.create_index('ix_word_page_queue_status', 'word_page_queue', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_word_page_queue_status', table_name='word_page_queue')
    op.drop_table('word_page_queue')
    op.drop_index('ix_word_pages_status_published', table_name='word_pages')
    op.drop_index('ix_word_pages_status', table_name='word_pages')
    op.drop_index('ix_word_pages_slug', table_name='word_pages')
    op.drop_table('word_pages')