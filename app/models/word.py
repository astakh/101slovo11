from sqlalchemy import BigInteger, Boolean, DateTime, Identity, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func, text
from datetime import datetime
from .base import Base

class Word(Base):
    __tablename__ = "words"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    lemma: Mapped[str] = mapped_column(String(64), nullable=False)
    lemma_key: Mapped[str] = mapped_column(String(64), nullable=False)
    pos: Mapped[str] = mapped_column(String(16), nullable=False)  # <-- Увеличено с 10 до 16
    level: Mapped[str | None] = mapped_column(String(2), nullable=True)
    translations: Mapped[list] = mapped_column(ARRAY(String), nullable=False)
    in_general: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    in_it: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    in_travel: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        UniqueConstraint("lemma_key", "pos", name="uq_words_lemma_key_pos"),
        Index("ix_words_level_general", "level", postgresql_where=text("in_general = true")),
        Index("ix_words_level_it", "level", postgresql_where=text("in_it = true")),
        Index("ix_words_level_travel", "level", postgresql_where=text("in_travel = true")),
    )