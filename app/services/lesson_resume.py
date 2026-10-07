"""Возобновление незавершённого урока."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.lesson import Lesson
from app.models.lesson_exercise import LessonExercise


async def get_resume_info(
    db: AsyncSession,
    user: User,
    lesson_id: int,
) -> dict:
    """
    Получает информацию для возобновления урока.

    Returns:
        {"lesson": Lesson, "exercise": LessonExercise | None}
    """
    stmt = select(Lesson).where(
        Lesson.id == lesson_id,
        Lesson.user_id == user.id,
    )
    result = await db.execute(stmt)
    lesson = result.scalar_one_or_none()

    if not lesson:
        raise ValueError("Урок не найден")

    if lesson.status == "completed":
        return {"lesson": lesson, "exercise": None, "completed": True}

    # Находим первое pending упражнение
    stmt_ex = (
        select(LessonExercise)
        .where(
            LessonExercise.lesson_id == lesson.id,
            LessonExercise.status == "pending",
        )
        .order_by(LessonExercise.order_index.asc())
        .limit(1)
    )
    result_ex = await db.execute(stmt_ex)
    exercise = result_ex.scalar_one_or_none()

    return {"lesson": lesson, "exercise": exercise, "completed": False}