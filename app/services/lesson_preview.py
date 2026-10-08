"""Подбор слов для урока с логикой level-up."""

import logging
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import User
from app.models.word import Word
from app.models.user_word import UserWord
from app.utils.clustering import cluster_words
from app.utils.datetime_utils import get_user_today
from app.llm.helpers import generate_sentences
from app.llm.gigachat import GigaChatError
from app.llm.validation import LlmUsage

logger = logging.getLogger(__name__)

# Порядок уровней для level-up.
_LEVEL_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"]


def _next_level(current: str) -> str | None:
    """Возвращает следующий уровень или None, если текущий — максимальный."""
    if current not in _LEVEL_ORDER:
        return None
    idx = _LEVEL_ORDER.index(current)
    if idx + 1 >= len(_LEVEL_ORDER):
        return None
    return _LEVEL_ORDER[idx + 1]


async def get_due_words(
    db: AsyncSession,
    user: User,
    next_lesson_number: int,
    *,
    limit: int,
) -> list[dict]:
    """
    Получает слова, подлежащие повторению.

    Args:
        limit: максимальное количество возвращаемых слов.
               Ограничение критично: без него в урок попадут все due-слова
               пользователя, даже если их больше words_per_lesson.
    """
    if limit <= 0:
        return []

    stmt = (
        select(UserWord, Word)
        .join(Word, UserWord.word_id == Word.id)
        .where(
            UserWord.user_id == user.id,
            UserWord.status == "active",
            UserWord.due_lesson_number <= next_lesson_number,
        )
        .order_by(UserWord.due_lesson_number.asc(), UserWord.id.asc())
        .limit(limit)
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
    count: int,
) -> list[dict]:
    """
    Подбирает новые слова для урока из глобальной базы.
    Исключает слова, уже добавленные пользователю.

    Args:
        count: точное (максимальное) количество слов.
    """
    if count <= 0:
        return []

    # ID слов, которые уже есть у пользователя (любой статус).
    stmt_existing = select(UserWord.word_id).where(UserWord.user_id == user.id)
    existing_ids = set(
        (await db.execute(stmt_existing)).scalars().all()
    )

    dictionary_code = user.dictionary_code or "general"
    dict_flag = {
        "general": Word.in_general,
        "it": Word.in_it,
        "travel": Word.in_travel,
    }.get(dictionary_code, Word.in_general)

    # Берём с запасом, чтобы отфильтровать уже имеющиеся.
    # Запас x3 покрывает случаи, когда многие слова уже добавлены.
    fetch_limit = max(count * 3, count + 50)

    stmt = (
        select(Word)
        .where(
            dict_flag == True,  # noqa: E712
            Word.level == level,
        )
        .order_by(Word.id.asc())
        .limit(fetch_limit)
    )
    words_rows = (await db.execute(stmt)).scalars().all()

    # Фильтруем уже добавленные.
    candidates = [w for w in words_rows if w.id not in existing_ids]

    # Строгий срез до count.
    candidates = candidates[:count]

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
        for w in candidates
    ]


async def build_lesson_preview(
    db: AsyncSession,
    user: User,
) -> dict:
    """
    Строит превью урока: подбор слов с level-up.

    Гарантирует: len(all_words) <= user.words_per_lesson.

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

    # 1. Набираем due_words (строго не больше N).
    due_words = await get_due_words(
        db, user, next_lesson_number, limit=N,
    )

    # 2. Определяем сколько новых нужно.
    need_new = N - len(due_words)
    new_words: list[dict] = []
    level_up = False
    new_level = None
    current_level = user.level or "A1"

    if need_new > 0:
        new_words = await get_new_words(db, user, current_level, need_new)

        # Если не хватает и уровень не максимальный — level-up.
        if len(new_words) < need_new and current_level != settings.MAX_LEVEL:
            next_lvl = _next_level(current_level)
            if next_lvl:
                level_up = True
                new_level = next_lvl
                remaining = need_new - len(new_words)
                extra_words = await get_new_words(db, user, next_lvl, remaining)
                new_words.extend(extra_words)

    all_words = due_words + new_words

    # 🔒 Защитный срез: гарантируем, что не больше N слов.
    # Срабатывает, если где-то в логике выше произошла ошибка.
    if len(all_words) > N:
        logger.warning(
            f"[PREVIEW] all_words ({len(all_words)}) > N ({N}). "
            f"Truncating. due={len(due_words)}, new={len(new_words)}"
        )
        # Приоритет у due-слов (повторение важнее новых).
        all_words = all_words[:N]
        # Корректируем new_words соответственно.
        new_words = [w for w in all_words if w.get("is_new")]

    # Определяем состояние.
    if not all_words:
        state = "no_words"
    elif need_new > 0 and len(new_words) < need_new:
        if current_level == settings.MAX_LEVEL:
            state = "dictionary_exhausted"
        else:
            # level-up помог или не помог — проверяем.
            state = "ready" if len(all_words) == N else "dictionary_exhausted"
    else:
        state = "ready"

    logger.info(
        f"[PREVIEW] user_id={user.id}, N={N}, due={len(due_words)}, "
        f"new={len(new_words)}, total={len(all_words)}, state={state}, "
        f"level_up={level_up}"
    )

    return {
        "due_words": due_words,
        "new_words": new_words,
        "all_words": all_words,
        "level_up": level_up,
        "new_level": new_level,
        "state": state,
        "next_lesson_number": next_lesson_number,
    }