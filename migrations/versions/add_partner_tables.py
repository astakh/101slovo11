"""add partner tables
Revision ID: b1c2d3e4f5g6
Revises: a1b2c3d4e5f6
Create Date: 2026-10-10 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b1c2d3e4f5g6'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # === Изменяем длину промокода с 6 до 9 символов ===
    op.alter_column(
        'promo_codes', 'code',
        existing_type=sa.String(length=6),
        type_=sa.String(length=9),
    )
    
    # === Таблица partners ===
    op.create_table('partners',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('partner_type', sa.String(length=20), nullable=False),
        sa.Column('inn', sa.String(length=20), nullable=True),
        sa.Column('payout_details', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', name='uq_partners_user_id')
    )
    op.create_index('ix_partners_user_id', 'partners', ['user_id'], unique=False)
    
    # === Таблица partner_invites ===
    op.create_table('partner_invites',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('token', sa.String(length=64), nullable=False),
        sa.Column('created_by', sa.BigInteger(), nullable=False),
        sa.Column('used_by_partner_id', sa.BigInteger(), nullable=True),
        sa.Column('is_used', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['used_by_partner_id'], ['partners.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token', name='uq_partner_invites_token')
    )
    op.create_index('ix_partner_invites_is_used', 'partner_invites', ['is_used'], unique=False)
    
    # === Таблица partner_earnings ===
    op.create_table('partner_earnings',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('partner_user_id', sa.BigInteger(), nullable=False),
        sa.Column('referred_user_id', sa.BigInteger(), nullable=False),
        sa.Column('payment_id', sa.BigInteger(), nullable=False),
        sa.Column('payment_amount_kop', sa.Integer(), nullable=False),
        sa.Column('commission_percent', sa.Integer(), nullable=False),
        sa.Column('earning_amount_kop', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['partner_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['referred_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['payment_id'], ['payments.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_partner_earnings_partner_user_id', 'partner_earnings', ['partner_user_id'], unique=False)
    op.create_index('ix_partner_earnings_status', 'partner_earnings', ['status'], unique=False)
    
    # === Добавляем status в promo_codes ===
    op.add_column('promo_codes', sa.Column('status', sa.String(length=16), nullable=False, server_default='approved'))
    op.create_index('ix_promo_codes_status', 'promo_codes', ['status'], unique=False)
    
    # === Обновляем существующие промокоды: ставим status='approved' ===
    op.execute("UPDATE promo_codes SET status = 'approved' WHERE status IS NULL OR status = ''")


def downgrade() -> None:
    op.drop_index('ix_promo_codes_status', table_name='promo_codes')
    op.drop_column('promo_codes', 'status')
    op.drop_index('ix_partner_earnings_status', table_name='partner_earnings')
    op.drop_index('ix_partner_earnings_partner_user_id', table_name='partner_earnings')
    op.drop_table('partner_earnings')
    op.drop_index('ix_partner_invites_is_used', table_name='partner_invites')
    op.drop_table('partner_invites')
    op.drop_index('ix_partners_user_id', table_name='partners')
    op.drop_table('partners')
    # === Возвращаем длину промокода к 6 ===
    op.alter_column(
        'promo_codes', 'code',
        existing_type=sa.String(length=9),
        type_=sa.String(length=6),
    )