"""Подбор слов для урока с логикой level-up."""

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.word import Word
from app.models.user_word import UserWord
from app.models.lesson import Lesson
from app.config import settings


LEVELS_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"]

# Маппинг dictionary_code → колонка в Word
DICT_COLUMN_MAP = {
    "general": Word.in_general,
    "it": Word.in_it,
    "travel": Word.in_travel,
}


def _next_level(current: str) -> str | None:
    """Возвращает следующий уровень или None если C2."""
    try:
        idx = LEVELS_ORDER.index(current)
    except ValueError:
        return None
    if idx >= len(LEVELS_ORDER) - 1:
        return None
    return LEVELS_ORDER[idx + 1]


async def get_due_words(
    db: AsyncSession,
    user: User,
    next_lesson_number: int,
) -> list[dict]:
    """Получает слова, подлежащие повторению."""
    stmt = (
        select(UserWord, Word)
        .join(Word, UserWord.word_id == Word.id)
        .where(
            UserWord.user_id == user.id,
            UserWord.status == "active",
            UserWord.due_lesson_number <= next_lesson_number,
        )
        .order_by(UserWord.due_lesson_number.asc(), UserWord.id.asc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    words = []
    for uw, w in rows:
        words.append({
            "word_id": w.id,
            "lemma": w.lemma,
            "pos": w.pos,
            "translations": w.translations,
            "user_word_id": uw.id,
            "stage": uw.stage,
            "is_new": False,
        })
    return words


async def get_new_words(
    db: AsyncSession,
    user: User,
    level: str,
    limit: int,
) -> list[dict]:
    """Получает новые слова для указанного уровня и словаря."""
    dict_column = DICT_COLUMN_MAP.get(user.dictionary_code, Word.in_general)

    # Подзапрос: ID слов, уже добавленных пользователем
    existing_subq = (
        select(UserWord.word_id)
        .where(UserWord.user_id == user.id)
        .scalar_subquery()
    )

    stmt = (
        select(Word)
        .where(
            dict_column == True,  # noqa: E712
            Word.level == level,
            Word.id.notin_(existing_subq),
        )
        .order_by(Word.id.asc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    words_rows = result.scalars().all()

    return [
        {
            "word_id": w.id,
            "lemma": w.lemma,
            "pos": w.pos,
            "translations": w.translations,
            "user_word_id": None,
            "stage": 0,
            "is_new": True,
        }
        for w in words_rows
    ]


async def build_lesson_preview(
    db: AsyncSession,
    user: User,
) -> dict:
    """
    Строит превью урока: подбор слов с level-up.

    Returns:
        {
            "due_words": [...],
            "new_words": [...],
            "all_words": [...],
            "level_up": bool,
            "new_level": str | None,
            "state": "ready" | "dictionary_exhausted" | "no_words",
        }
    """
    N = user.words_per_lesson
    next_lesson_number = user.last_lesson_number + 1

    # 1. Набираем due_words
    due_words = await get_due_words(db, user, next_lesson_number)

    # 2. Определяем сколько новых нужно
    need_new = N - len(due_words)
    new_words: list[dict] = []
    level_up = False
    new_level = None
    current_level = user.level or "A1"

    if need_new > 0:
        new_words = await get_new_words(db, user, current_level, need_new)

        # Если не хватает и уровень не максимальный — level-up
        if len(new_words) < need_new and current_level != settings.MAX_LEVEL:
            next_lvl = _next_level(current_level)
            if next_lvl:
                level_up = True
                new_level = next_lvl
                remaining = need_new - len(new_words)
                extra_words = await get_new_words(db, user, next_lvl, remaining)
                new_words.extend(extra_words)

    all_words = due_words + new_words

    # Определяем состояние
    if not all_words:
        if current_level == settings.MAX_LEVEL:
            state = "dictionary_exhausted"
        else:
            state = "dictionary_exhausted"
    else:
        state = "ready"

    return {
        "due_words": due_words,
        "new_words": new_words,
        "all_words": all_words,
        "level_up": level_up,
        "new_level": new_level,
        "state": state,
        "next_lesson_number": next_lesson_number,
    }