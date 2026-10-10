from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Identity, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from datetime import datetime
from .base import Base


class PromoCode(Base):
    __tablename__ = "promo_codes"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(9), unique=True, nullable=False, index=True)
    owner_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # "user_referral" | "partner" | "marketing"
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="user_referral")
    # "pending" | "approved" | "disabled" (для partner-кодов)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="approved")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_promo_codes_owner", "owner_user_id"),
        Index("ix_promo_codes_status", "status"),
    )