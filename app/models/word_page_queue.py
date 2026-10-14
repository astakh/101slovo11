# app/models/word_page_queue.py
"""Модель очереди слов для генерации страниц."""
from sqlalchemy import (
    BigInteger, DateTime, ForeignKey, Identity, Index,
    SmallInteger, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from datetime import datetime
from .base import Base


class WordPageQueue(Base):
    __tablename__ = "word_page_queue"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    word_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("words.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="queued"
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Связь со словом
    word = relationship("Word", foreign_keys=[word_id], lazy="joined")

    __table_args__ = (
        UniqueConstraint("word_id", name="uq_word_page_queue_word_id"),
        Index("ix_word_page_queue_status", "status"),
    )