from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Index, Integer, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func, text
from datetime import datetime
from .base import Base

class UserWord(Base):
    __tablename__ = "user_words"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    word_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("words.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active")
    stage: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    due_lesson_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="dictionary")
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "word_id", name="uq_user_words_user_word"),
        Index("ix_user_words_user_status_due", "user_id", "status", "due_lesson_number"),
        Index("ix_user_words_user_due_active", "user_id", "due_lesson_number", postgresql_where=text("status = 'active'")),
    )