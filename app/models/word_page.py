# app/models/word_page.py
"""Модель страницы слова (SEO-страница с разбором слова от LLM)."""
from sqlalchemy import (
    BigInteger, DateTime, ForeignKey, Identity, Index,
    Integer, String, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from datetime import datetime
from .base import Base


class WordPage(Base):
    __tablename__ = "word_pages"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    word_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("words.id", ondelete="CASCADE"),
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    meta_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    meta_description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="draft"
    )
    view_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    gen_prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gen_completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Связь со словом
    word = relationship("Word", foreign_keys=[word_id], lazy="joined")

    __table_args__ = (
        UniqueConstraint("word_id", name="uq_word_pages_word_id"),
        UniqueConstraint("slug", name="uq_word_pages_slug"),
        Index("ix_word_pages_slug", "slug"),
        Index("ix_word_pages_status", "status"),
        Index("ix_word_pages_status_published", "status", "published_at"),
    )