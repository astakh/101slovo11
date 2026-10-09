from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Identity, Integer, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from datetime import datetime
from .base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timezone_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_onboarded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    level: Mapped[str | None] = mapped_column(String(2), nullable=True)
    dictionary_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    words_per_lesson: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=5)
    daily_lesson_limit: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    last_lesson_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # === Monetization fields ===
    # Кто пригласил этого пользователя (для реферальной программы)
    referred_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Счётчик попыток ввода промокода (антифрод, макс 3)
    promo_code_attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())