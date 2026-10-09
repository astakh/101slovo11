from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Identity, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from datetime import datetime
from .base import Base


class PromoCode(Base):
    __tablename__ = "promo_codes"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # Уникальный код, 6 символов (автогенерация)
    code: Mapped[str] = mapped_column(String(6), unique=True, nullable=False, index=True)
    owner_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # "user_referral" | "blogger" | "marketing"
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="user_referral")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_promo_codes_owner", "owner_user_id"),
    )