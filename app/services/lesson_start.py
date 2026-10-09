"""Идемпотентный старт урока с вызовом LLM."""
import logging
from datetime import datetime, timezone
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import User
from app.models.lesson import Lesson
from app.models.lesson_exercise import LessonExercise
from app.models.user_word import UserWord
from app.models.word import Word
from app.models.event import Event
from app.config import settings
from app.utils.clustering import cluster_words
from app.utils.datetime_utils import get_user_today
from app.services.paywall import check_lesson_access, get_effective_daily_limit
from app.llm.helpers import generate_sentences
from app.llm.gigachat import GigaChatError
from app.llm.validation import LlmUsage

logger = logging.getLogger(__name__)


class LessonStartError(Exception):
    """Ошибка при старте урока."""
    def __init__(self, message: str, code: str = "lesson_start_error"):
        super().__init__(message)
        self.code = code


async def start_lesson(
    db: AsyncSession,
    user: User,
    *,
    idempotency_key: str,
    word_ids: list[int],
) -> Lesson:
    """
    Идемпотентный старт урока.
    1. Проверка идемпотентности.
    2. Проверка незавершённого урока.
    3. Проверка пейволла (общий лимит для freemium).
    4. Проверка дневного лимита.
    5. 🔒 Проверка количества слов (<= words_per_lesson).
    6. Кластеризация слов.
    7. Вызов LLM.
    8. Транзакция: создание записей.
    Returns:
        Созданный или существующий Lesson.
    Raises:
        LessonStartError: при ошибке.
        GigaChatError: при ошибке LLM.
    """
    # 1. Идемпотентность
    stmt_idem = select(Lesson).where(
        Lesson.user_id == user.id,
        Lesson.idempotency_key == idempotency_key,
    )
    result_idem = await db.execute(stmt_idem)
    existing_lesson = result_idem.scalar_one_or_none()

    if existing_lesson:
        if existing_lesson.status == "in_progress":
            return existing_lesson

    # 2. Проверка незавершённого урока
    stmt_in_progress = select(Lesson).where(
        Lesson.user_id == user.id,
        Lesson.status == "in_progress",
    )
    result_ip = await db.execute(stmt_in_progress)
    in_progress = result_ip.scalar_one_or_none()

    if in_progress:
        raise LessonStartError(
            "У вас есть незавершённый урок. Завершите его или продолжите.",
            code="in_progress_exists",
        )

    # 3. Проверка пейволла (общий лимит для freemium)
    access = await check_lesson_access(db, user)
    if not access["allowed"]:
        raise LessonStartError(
            "Бесплатные уроки исчерпаны. Подключите Premium для продолжения.",
            code="free_limit_reached",
        )

    # 4. Проверка дневного лимита
    premium = access["is_premium"]
    effective_daily_limit = get_effective_daily_limit(user, premium)

    today = get_user_today(user.timezone)
    stmt_today = select(func.count(Lesson.id)).where(
        Lesson.user_id == user.id,
        Lesson.started_local_date == today,
    )
    result_today = await db.execute(stmt_today)
    lessons_today = result_today.scalar_one_or_none() or 0

    if lessons_today >= effective_daily_limit:
        raise LessonStartError(
            "Дневной лимит уроков исчерпан",
            code="limit_reached",
        )

    # 🔒 5. Проверка количества слов
    if not word_ids:
        raise LessonStartError("Слова не выбраны", code="no_words")

    if len(word_ids) > user.words_per_lesson:
        logger.warning(
            f"[START] user_id={user.id} requested {len(word_ids)} words, "
            f"but words_per_lesson={user.words_per_lesson}. Truncating."
        )
        word_ids = word_ids[: user.words_per_lesson]

    # 6. Загружаем слова для кластеризации
    stmt_words = select(Word).where(Word.id.in_(word_ids))
    result_words = await db.execute(stmt_words)
    words = result_words.scalars().all()

    if not words:
        raise LessonStartError("Слова не найдены", code="words_not_found")

    found_ids = {w.id for w in words}
    if found_ids != set(word_ids):
        missing = set(word_ids) - found_ids
        logger.warning(f"[START] Missing words: {missing}")

    word_dicts = [
        {
            "word_id": w.id,
            "lemma": w.lemma,
            "pos": w.pos,
            "translations": w.translations,
        }
        for w in words
    ]

    # 7. Кластеризация
    next_lesson_number = user.last_lesson_number + 1
    groups = cluster_words(word_dicts, user.id, next_lesson_number)

    # 8. Вызов LLM (ВНЕ транзакции)
    exercises_data, usage = await generate_sentences(
        db,
        level=user.level or "A1",
        word_groups=groups,
        user_id=user.id,
    )

    # 9. Транзакция: создаём записи
    stmt_user_lock = select(User).where(User.id == user.id).with_for_update()
    locked_user = (await db.execute(stmt_user_lock)).scalar_one()

    # Повторная проверка дневного лимита (под блокировкой)
    result_today2 = await db.execute(stmt_today)
    lessons_today2 = result_today2.scalar_one_or_none() or 0
    if lessons_today2 >= effective_daily_limit:
        raise LessonStartError(
            "Дневной лимит уроков исчерпан",
            code="limit_reached",
        )

    # Повторная проверка пейволла (под блокировкой)
    access2 = await check_lesson_access(db, locked_user)
    if not access2["allowed"]:
        raise LessonStartError(
            "Бесплатные уроки исчерпаны. Подключите Premium для продолжения.",
            code="free_limit_reached",
        )

    locked_user.last_lesson_number = next_lesson_number

    lesson = Lesson(
        user_id=locked_user.id,
        lesson_number=next_lesson_number,
        idempotency_key=idempotency_key,
        status="in_progress",
        started_local_date=today,
        gen_prompt_tokens=usage.prompt_tokens,
        gen_completion_tokens=usage.completion_tokens,
        gen_total_tokens=usage.total_tokens,
    )
    db.add(lesson)
    await db.flush()

    for idx, ex_data in enumerate(exercises_data):
        exercise = LessonExercise(
            lesson_id=lesson.id,
            order_index=idx,
            target_sentence=ex_data["target_sentence"],
            reference_translation=ex_data["reference_translation"],
            status="pending",
            target_words=ex_data.get("target_words", []),
        )
        db.add(exercise)

    for wd in word_dicts:
        stmt_uw = select(UserWord).where(
            UserWord.user_id == locked_user.id,
            UserWord.word_id == wd["word_id"],
        )
        result_uw = await db.execute(stmt_uw)
        existing_uw = result_uw.scalar_one_or_none()

        if not existing_uw:
            uw = UserWord(
                user_id=locked_user.id,
                word_id=wd["word_id"],
                status="active",
                stage=0,
                due_lesson_number=next_lesson_number + 1,
                source="lesson",
            )
            db.add(uw)

    event = Event(
        user_id=locked_user.id,
        type="lesson_started",
        payload={
            "lesson_id": lesson.id,
            "lesson_number": next_lesson_number,
            "words_count": len(word_dicts),
        },
    )
    db.add(event)
    await db.flush()

    logger.info(
        f"[START] Lesson #{next_lesson_number} created for user_id={user.id} "
        f"with {len(word_dicts)} words"
    )

    return lesson