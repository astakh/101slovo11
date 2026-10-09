from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from datetime import datetime
from .base import Base


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # "monthly" | "six_months"
    plan: Mapped[str] = mapped_column(String(20), nullable=False)
    amount_kop: Mapped[int] = mapped_column(Integer, nullable=False)
    # "pending" | "succeeded" | "failed" | "refunded"
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    # ID платежа в ЮKassa
    yookassa_payment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Описание для чека
    description: Mapped[str | None] = mapped_column(String(256), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_payments_user_id", "user_id"),
        Index("ix_payments_status", "status"),
        Index("ix_payments_yookassa_id", "yookassa_payment_id"),
    )