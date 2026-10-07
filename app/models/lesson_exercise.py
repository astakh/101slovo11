from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Index, Integer, SmallInteger, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func, text
from datetime import datetime
from .base import Base

class LessonExercise(Base):
    __tablename__ = "lesson_exercises"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    lesson_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False)
    order_index: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    target_sentence: Mapped[str] = mapped_column(String(200), nullable=False)
    reference_translation: Mapped[str] = mapped_column(String(300), nullable=False)
    user_translation: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    target_words: Mapped[dict | list] = mapped_column(JSON, nullable=False, server_default=text("'[]'::json"))
    suggested_words: Mapped[dict | list] = mapped_column(JSON, nullable=False, server_default=text("'[]'::json"))
    nontarget_words: Mapped[dict | list] = mapped_column(JSON, nullable=False, server_default=text("'[]'::json"))
    eval_prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    eval_completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("lesson_id", "order_index", name="uq_exercises_lesson_order"),
        Index("ix_exercises_pending", "lesson_id", "order_index", postgresql_where=text("status = 'pending'")),
    )