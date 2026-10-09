"""add monetization tables

Revision ID: a1b2c3d4e5f6
Revises: 5a8c3d7e9f12
Create Date: 2026-10-09 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '5a8c3d7e9f12'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # === Таблица payments ===
    op.create_table('payments',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('plan', sa.String(length=20), nullable=False),
        sa.Column('amount_kop', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('yookassa_payment_id', sa.String(length=64), nullable=True),
        sa.Column('description', sa.String(length=256), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_payments_user_id', 'payments', ['user_id'], unique=False)
    op.create_index('ix_payments_status', 'payments', ['status'], unique=False)
    op.create_index('ix_payments_yookassa_id', 'payments', ['yookassa_payment_id'], unique=False)

    # === Таблица subscriptions ===
    op.create_table('subscriptions',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('plan', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('source', sa.String(length=16), nullable=False),
        sa.Column('payment_id', sa.BigInteger(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('canceled_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['payment_id'], ['payments.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_subscriptions_user_status', 'subscriptions', ['user_id', 'status'], unique=False)
    op.create_index('ix_subscriptions_expires_at', 'subscriptions', ['expires_at'], unique=False)

    # === Таблица promo_codes ===
    op.create_table('promo_codes',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('code', sa.String(length=6), nullable=False),
        sa.Column('owner_user_id', sa.BigInteger(), nullable=False),
        sa.Column('type', sa.String(length=20), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('used_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code', name='uq_promo_codes_code')
    )
    op.create_index('ix_promo_codes_owner', 'promo_codes', ['owner_user_id'], unique=False)

    # === Таблица referrals ===
    op.create_table('referrals',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('referrer_user_id', sa.BigInteger(), nullable=False),
        sa.Column('referred_user_id', sa.BigInteger(), nullable=False),
        sa.Column('promo_code_id', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('rewarded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['referrer_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['referred_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['promo_code_id'], ['promo_codes.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('referred_user_id', name='uq_referrals_referred_user')
    )
    op.create_index('ix_referrals_referrer', 'referrals', ['referrer_user_id'], unique=False)
    op.create_index('ix_referrals_status', 'referrals', ['status'], unique=False)

    # === Новые поля в users ===
    op.add_column('users', sa.Column('referred_by_user_id', sa.BigInteger(), nullable=True))
    op.add_column('users', sa.Column('promo_code_attempts', sa.SmallInteger(), nullable=False, server_default='0'))
    op.create_foreign_key(
        'fk_users_referred_by', 'users', 'users',
        ['referred_by_user_id'], ['id'], ondelete='SET NULL'
    )


def downgrade() -> None:
    op.drop_constraint('fk_users_referred_by', 'users', type_='foreignkey')
    op.drop_column('users', 'promo_code_attempts')
    op.drop_column('users', 'referred_by_user_id')

    op.drop_index('ix_referrals_status', table_name='referrals')
    op.drop_index('ix_referrals_referrer', table_name='referrals')
    op.drop_table('referrals')

    op.drop_index('ix_promo_codes_owner', table_name='promo_codes')
    op.drop_table('promo_codes')

    op.drop_index('ix_subscriptions_expires_at', table_name='subscriptions')
    op.drop_index('ix_subscriptions_user_status', table_name='subscriptions')
    op.drop_table('subscriptions')

    op.drop_index('ix_payments_yookassa_id', table_name='payments')
    op.drop_index('ix_payments_status', table_name='payments')
    op.drop_index('ix_payments_user_id', table_name='payments')
    op.drop_table('payments')