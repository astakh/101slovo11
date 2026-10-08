"""Сервис статистики расхода токенов для админки."""

from datetime import date, timedelta
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.lesson import Lesson
from app.models.lesson_exercise import LessonExercise


async def get_token_stats(db: AsyncSession) -> dict:
    """
    Возвращает сводную статистику расхода токенов по периодам.

    Периоды:
    - today: сегодня
    - week: последние 7 дней
    - month: последние 30 дней
    - all: всё время

    Returns:
        {
            "today": {...},
            "week": {...},
            "month": {...},
            "all": {...},
        }
    """
    today = date.today()

    periods = [
        ("today", today, "Сегодня"),
        ("week", today - timedelta(days=7), "7 дней"),
        ("month", today - timedelta(days=30), "30 дней"),
        ("all", None, "Всё время"),
    ]

    stats: dict = {}

    for period_key, start_date, label in periods:
        # --- Генерация предложений (таблица lessons) ---
        gen_query = select(
            func.coalesce(func.sum(Lesson.gen_prompt_tokens), 0),
            func.coalesce(func.sum(Lesson.gen_completion_tokens), 0),
            func.count(Lesson.id),
        )
        if start_date is not None:
            gen_query = gen_query.where(Lesson.started_local_date >= start_date)

        gen_result = await db.execute(gen_query)
        gen_prompt, gen_completion, lessons_count = gen_result.one()

        # --- Оценка переводов (таблица lesson_exercises, JOIN с lessons) ---
        eval_query = (
            select(
                func.coalesce(func.sum(LessonExercise.eval_prompt_tokens), 0),
                func.coalesce(func.sum(LessonExercise.eval_completion_tokens), 0),
            )
            .join(Lesson, LessonExercise.lesson_id == Lesson.id)
        )
        if start_date is not None:
            eval_query = eval_query.where(Lesson.started_local_date >= start_date)

        eval_result = await db.execute(eval_query)
        eval_prompt, eval_completion = eval_result.one()

        # --- Итоги ---
        gen_prompt = gen_prompt or 0
        gen_completion = gen_completion or 0
        eval_prompt = eval_prompt or 0
        eval_completion = eval_completion or 0
        lessons_count = lessons_count or 0

        total_prompt = gen_prompt + eval_prompt
        total_completion = gen_completion + eval_completion
        total_tokens = total_prompt + total_completion
        avg_per_lesson = round(total_tokens / lessons_count) if lessons_count > 0 else 0

        stats[period_key] = {
            "label": label,
            "gen_prompt_tokens": gen_prompt,
            "gen_completion_tokens": gen_completion,
            "eval_prompt_tokens": eval_prompt,
            "eval_completion_tokens": eval_completion,
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "total_tokens": total_tokens,
            "lessons_count": lessons_count,
            "avg_tokens_per_lesson": avg_per_lesson,
        }

    return stats