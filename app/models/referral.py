from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from datetime import datetime
from .base import Base


class Referral(Base):
    __tablename__ = "referrals"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    referrer_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    referred_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    promo_code_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("promo_codes.id", ondelete="CASCADE"), nullable=False
    )
    # "pending" | "rewarded"
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    rewarded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # Один пользователь может быть приглашён только одним реферером
        UniqueConstraint("referred_user_id", name="uq_referrals_referred_user"),
        Index("ix_referrals_referrer", "referrer_user_id"),
        Index("ix_referrals_status", "status"),
    )