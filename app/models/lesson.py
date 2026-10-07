from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Identity, Index, Integer, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func, text
from datetime import datetime, date
from .base import Base

class Lesson(Base):
    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    lesson_number: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="in_progress")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_local_date: Mapped[date] = mapped_column(Date, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_local_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    gen_prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gen_completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "lesson_number", name="uq_lessons_user_number"),
        UniqueConstraint("user_id", "idempotency_key", name="uq_lessons_user_idem_key"),
        Index("ix_lessons_user_in_progress", "user_id", unique=True, postgresql_where=text("status = 'in_progress'")),
        Index("ix_lessons_user_started", "user_id", "started_local_date"),
        Index("ix_lessons_user_completed", "user_id", "completed_local_date"),
    )