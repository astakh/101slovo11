from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user import User
from app.models.event import Event

APP_TIMEZONE = "Europe/Moscow"


async def complete_onboarding(
    db: AsyncSession,
    user: User,
    level: str,
    dictionary_code: str,
    words_per_lesson: int,
    daily_lesson_limit: int
) -> None:
    # Перезагружаем пользователя в текущей сессии
    stmt = select(User).where(User.id == user.id)
    result = await db.execute(stmt)
    db_user = result.scalar_one()

    if db_user.is_onboarded:
        raise ValueError("Онбординг уже пройден")

    db_user.level = level
    db_user.dictionary_code = dictionary_code
    db_user.timezone = APP_TIMEZONE
    db_user.words_per_lesson = words_per_lesson
    db_user.daily_lesson_limit = daily_lesson_limit
    db_user.is_onboarded = True

    event = Event(user_id=db_user.id, type="onboarding_completed")
    db.add(event)

    await db.commit()
    await db.refresh(db_user)