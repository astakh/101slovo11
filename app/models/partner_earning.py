from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from datetime import datetime
from .base import Base


class PartnerEarning(Base):
    __tablename__ = "partner_earnings"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    partner_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    referred_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    payment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("payments.id", ondelete="CASCADE"), nullable=False
    )
    payment_amount_kop: Mapped[int] = mapped_column(Integer, nullable=False)
    commission_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    earning_amount_kop: Mapped[int] = mapped_column(Integer, nullable=False)
    # "pending" | "paid" | "canceled"
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_partner_earnings_partner_user_id", "partner_user_id"),
        Index("ix_partner_earnings_status", "status"),
    )