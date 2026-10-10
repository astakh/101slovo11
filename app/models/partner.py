from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Identity, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from datetime import datetime
from .base import Base


class Partner(Base):
    __tablename__ = "partners"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    # "self_employed" | "individual" | "company"
    partner_type: Mapped[str] = mapped_column(String(20), nullable=False)
    inn: Mapped[str | None] = mapped_column(String(20), nullable=True)
    payout_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_partners_user_id", "user_id"),
    )