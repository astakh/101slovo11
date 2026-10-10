"""increase promo code length to 9
Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5g6
Create Date: 2026-10-10 14:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'c2d3e4f5a6b7'
down_revision = 'b1c2d3e4f5g6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        'promo_codes', 'code',
        existing_type=sa.String(length=6),
        type_=sa.String(length=9),
    )


def downgrade() -> None:
    op.alter_column(
        'promo_codes', 'code',
        existing_type=sa.String(length=9),
        type_=sa.String(length=6),
    )