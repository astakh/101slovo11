"""Оценка перевода пользователя с обновлением SRS."""
import logging
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.user import User
from app.models.lesson import Lesson
from app.models.lesson_exercise import LessonExercise
from app.models.user_word import UserWord
from app.models.word import Word
from app.models.event import Event
from app.utils.srs import srs_update
from app.utils.text_validation import validate_user_translation, compute_lemma_key
from app.llm.helpers import evaluate_translation as llm_evaluate
from app.llm.gigachat import GigaChatError

logger = logging.getLogger(__name__)


class LessonEvaluateError(Exception):
    """Ошибка при оценке перевода."""

    def __init__(self, message: str, code: str = "evaluate_error"):
        super().__init__(message)
        self.code = code


async def _find_user_word(
    db: AsyncSession,
    user: User,
    *,
    lemma: str,
    pos: str | None,
) -> UserWord | None:
    """
    Находит запись пользователя в `user_words` по лемме слова.
    """
    if not lemma:
        return None

    lemma_key = compute_lemma_key(lemma)

    stmt_word = select(Word).where(Word.lemma_key == lemma_key)
    if pos:
        stmt_word = stmt_word.where(Word.pos == pos)
    stmt_word = stmt_word.limit(1)
    word = (await db.execute(stmt_word)).scalar_one_or_none()

    if not word and pos:
        stmt_word = select(Word).where(Word.lemma_key == lemma_key).limit(1)
        word = (await db.execute(stmt_word)).scalar_one_or_none()

    if not word:
        return None

    stmt_uw = select(UserWord).where(
        UserWord.user_id == user.id,
        UserWord.word_id == word.id,
    )
    return (await db.execute(stmt_uw)).scalar_one_or_none()


async def _filter_suggested_words(
    db: AsyncSession,
    user: User,
    suggested_words: list[dict],
) -> list[dict]:
    """
    ✅ ФИКС: Фильтрует предложенные слова, исключая те,
    которые уже есть у пользователя в словаре (любой статус).

    Логика:
    - Для каждого предложенного слова ищем его в таблице `words` по lemma.
    - Если слово найдено и УЖЕ есть в `user_words` пользователя — исключаем.
    - Если слово не найдено в `words` — тоже исключаем (нельзя добавить
      то, чего нет в базе; добавление через suggestions работает только
      с существующими словами).

    Args:
        db: сессия БД.
        user: пользователь.
        suggested_words: список слов от LLM.

    Returns:
        Отфильтрованный список (только новые для пользователя слова,
        существующие в таблице words).
    """
    if not suggested_words:
        return []

    filtered = []

    for sw in suggested_words:
        lemma = sw.get("lemma", "")
        if not lemma:
            continue

        lemma_key = compute_lemma_key(lemma)

        # Ищем слово в глобальной таблице
        stmt_word = select(Word).where(Word.lemma_key == lemma_key).limit(1)
        word = (await db.execute(stmt_word)).scalar_one_or_none()

        if not word:
            # Слова нет в базе — не можем добавить, пропускаем
            logger.debug(
                f"[FILTER] Suggested word '{lemma}' not in words table, skipping"
            )
            continue

        # Проверяем, есть ли уже у пользователя
        stmt_uw = select(UserWord).where(
            UserWord.user_id == user.id,
            UserWord.word_id == word.id,
        )
        existing_uw = (await db.execute(stmt_uw)).scalar_one_or_none()

        if existing_uw:
            # Слово уже в словаре пользователя (любой статус) — исключаем
            logger.debug(
                f"[FILTER] Suggested word '{lemma}' already in user_words "
                f"(status={existing_uw.status}), skipping"
            )
            continue

        # Слово новое и есть в базе — оставляем
        filtered.append({**sw, "word_id": word.id})

    return filtered


async def evaluate_exercise(
    db: AsyncSession,
    user: User,
    *,
    exercise_id: int,
    user_translation: str,
) -> dict:
    """
    Оценивает перевод упражнения.
    """
    # 1. Загружаем упражнение и урок
    stmt_ex = select(LessonExercise).where(LessonExercise.id == exercise_id)
    result_ex = await db.execute(stmt_ex)
    exercise = result_ex.scalar_one_or_none()

    if not exercise:
        raise LessonEvaluateError("Упражнение не найдено", code="not_found")

    stmt_lesson = select(Lesson).where(Lesson.id == exercise.lesson_id)
    result_lesson = await db.execute(stmt_lesson)
    lesson = result_lesson.scalar_one_or_none()

    if not lesson or lesson.user_id != user.id:
        raise LessonEvaluateError("Доступ запрещён", code="forbidden")

    # Идемпотентность: если уже оценено — возвращаем сохранённые данные
    if exercise.status == "evaluated":
        return _build_result(exercise, lesson, is_repeat=True)

    # Проверка статуса урока
    if lesson.status != "in_progress":
        raise LessonEvaluateError("Урок уже завершён", code="lesson_completed")

    # Проверка порядка: это должно быть первое pending-упражнение
    stmt_first_pending = (
        select(LessonExercise)
        .where(
            LessonExercise.lesson_id == lesson.id,
            LessonExercise.status == "pending",
        )
        .order_by(LessonExercise.order_index.asc())
        .limit(1)
    )
    result_fp = await db.execute(stmt_first_pending)
    first_pending = result_fp.scalar_one_or_none()

    if not first_pending or first_pending.id != exercise.id:
        raise LessonEvaluateError("Нарушена последовательность упражнений", code="order_violation")

    # 2. Валидация ввода
    try:
        clean_translation = validate_user_translation(user_translation)
    except ValueError as e:
        raise LessonEvaluateError(str(e), code="validation_error")

    # 3. Вызов LLM
    target_words = exercise.target_words or []

    evaluation, usage = await llm_evaluate(
        db,
        target_sentence=exercise.target_sentence,
        reference_translation=exercise.reference_translation,
        target_words=target_words,
        user_translation=clean_translation,
        user_id=user.id,
    )

    # 4. Блокировка упражнения
    stmt_ex_lock = (
        select(LessonExercise)
        .where(LessonExercise.id == exercise.id)
        .with_for_update()
    )
    result_ex_lock = await db.execute(stmt_ex_lock)
    locked_exercise = result_ex_lock.scalar_one()

    locked_exercise.user_translation = clean_translation
    locked_exercise.status = "evaluated"
    locked_exercise.evaluated_at = datetime.now(timezone.utc)
    locked_exercise.eval_prompt_tokens = usage.prompt_tokens
    locked_exercise.eval_completion_tokens = usage.completion_tokens
    locked_exercise.eval_total_tokens = usage.total_tokens

    # 5. Обработка оценок целевых слов
    evaluations = evaluation.get("evaluations", [])
    eval_map = {e["lemma"].casefold(): e for e in evaluations}

    updated_target_words = []
    for tw in target_words:
        lemma = tw.get("lemma", "")
        pos = tw.get("pos")
        lemma_key = lemma.casefold()

        eval_item = eval_map.get(lemma_key, {})
        word_status = eval_item.get("status", "learning")

        if word_status == "mastered":
            srs_result = "correct"
        elif word_status == "failed":
            srs_result = "incorrect"
        else:
            srs_result = "typo"

        uw = await _find_user_word(db, user, lemma=lemma, pos=pos)
        word_id = uw.word_id if uw else None

        if uw:
            new_stage, new_due, new_status = srs_update(
                uw.stage, srs_result, lesson.lesson_number
            )
            uw.stage = new_stage
            uw.due_lesson_number = new_due
            uw.status = new_status
            uw.last_reviewed_at = datetime.now(timezone.utc)

        updated_tw = {
            **tw,
            "word_id": word_id,
            "eval_status": word_status,
            "eval_comment": eval_item.get("comment", ""),
            "srs_result": srs_result,
        }
        updated_target_words.append(updated_tw)

    locked_exercise.target_words = updated_target_words
    flag_modified(locked_exercise, "target_words")

    # 6. ✅ ФИКС: Обработка suggested_words с фильтрацией
    suggested = evaluation.get("suggested_words", [])
    logger.info(f"[SERVICE EVAL] Raw suggested from LLM: {suggested}")

    # Фильтруем: исключаем слова, уже есть у пользователя,
    # и слова, которых нет в таблице words.
    filtered_suggested = await _filter_suggested_words(db, user, suggested)

    logger.info(
        f"[SERVICE EVAL] After filtering: {len(filtered_suggested)} "
        f"(was {len(suggested)} from LLM)"
    )

    suggested_with_state = [
        {**s, "state": "pending"}
        for s in filtered_suggested
    ]

    locked_exercise.suggested_words = suggested_with_state
    flag_modified(locked_exercise, "suggested_words")

    # 7. Проверка завершения урока
    stmt_remaining = (
        select(LessonExercise)
        .where(
            LessonExercise.lesson_id == lesson.id,
            LessonExercise.status == "pending",
            LessonExercise.id != exercise.id,
        )
        .limit(1)
    )
    result_remaining = await db.execute(stmt_remaining)
    has_remaining = result_remaining.scalar_one_or_none() is not None

    lesson_completed = False
    if not has_remaining:
        lesson.status = "completed"
        lesson.completed_at = datetime.now(timezone.utc)
        lesson.completed_local_date = lesson.started_local_date
        lesson_completed = True

        event = Event(
            user_id=user.id,
            type="lesson_completed",
            payload={"lesson_id": lesson.id, "lesson_number": lesson.lesson_number},
        )
        db.add(event)

    await db.flush()

    return {
        "exercise": locked_exercise,
        "evaluation": evaluation,
        "target_words": updated_target_words,
        "suggested_words": suggested_with_state,
        "lesson_completed": lesson_completed,
        "lesson_id": lesson.id,
        "is_repeat": False,
    }


def _build_result(exercise: LessonExercise, lesson: Lesson, *, is_repeat: bool) -> dict:
    """Строит результат из уже сохранённых данных (для идемпотентности)."""
    return {
        "exercise": exercise,
        "evaluation": {
            "status": "correct",
            "feedback": "Результат уже сохранён.",
            "evaluations": [],
            "suggested_words": [],
            "translation_errors": [],
        },
        "target_words": exercise.target_words or [],
        "suggested_words": exercise.suggested_words or [],
        "lesson_completed": lesson.status == "completed",
        "lesson_id": lesson.id,
        "is_repeat": is_repeat,
    }