"""Итоги урока."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.lesson import Lesson
from app.models.lesson_exercise import LessonExercise
from app.utils.streak import calculate_streak
from app.utils.datetime_utils import get_user_today


async def get_lesson_summary(
    db: AsyncSession,
    user: User,
    lesson_id: int,
) -> dict:
    """
    Формирует итоги завершённого урока.

    Returns:
        Словарь с метриками для шаблона.
    """
    # Загружаем урок
    stmt = select(Lesson).where(
        Lesson.id == lesson_id,
        Lesson.user_id == user.id,
    )
    result = await db.execute(stmt)
    lesson = result.scalar_one_or_none()

    if not lesson:
        raise ValueError("Урок не найден")

    # Загружаем упражнения
    stmt_ex = (
        select(LessonExercise)
        .where(LessonExercise.lesson_id == lesson.id)
        .order_by(LessonExercise.order_index.asc())
    )
    result_ex = await db.execute(stmt_ex)
    exercises = result_ex.scalars().all()

    # Подсчёт метрик
    total_words = 0
    correct_words = 0
    typo_words = 0
    failed_words = 0

    for ex in exercises:
        for tw in (ex.target_words or []):
            total_words += 1
            eval_status = tw.get("eval_status", "learning")
            if eval_status == "mastered":
                correct_words += 1
            elif eval_status == "failed":
                failed_words += 1
            else:
                typo_words += 1

    # Токены
    total_prompt_tokens = lesson.gen_prompt_tokens or 0
    total_completion_tokens = lesson.gen_completion_tokens or 0
    for ex in exercises:
        total_prompt_tokens += ex.eval_prompt_tokens or 0
        total_completion_tokens += ex.eval_completion_tokens or 0

    # Стрик
    today = get_user_today(user.timezone)
    stmt_dates = select(Lesson.started_local_date).where(
        Lesson.user_id == user.id,
        Lesson.completed_local_date.isnot(None),
    )
    result_dates = await db.execute(stmt_dates)
    completed_dates = [row[0] for row in result_dates]
    streak = calculate_streak(completed_dates, today)

    return {
        "lesson": lesson,
        "exercises": exercises,
        "total_words": total_words,
        "correct_words": correct_words,
        "typo_words": typo_words,
        "failed_words": failed_words,
        "total_exercises": len(exercises),
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": total_completion_tokens,
        "streak": streak,
    }