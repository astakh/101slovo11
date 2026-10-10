from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Identity, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from datetime import datetime
from .base import Base


class PartnerInvite(Base):
    __tablename__ = "partner_invites"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_by: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    used_by_partner_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("partners.id", ondelete="SET NULL"), nullable=True
    )
    is_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_partner_invites_is_used", "is_used"),
    )