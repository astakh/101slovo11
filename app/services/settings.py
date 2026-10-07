"""Сервис для обновления настроек пользователя."""
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.user import User
from app.models.event import Event

TIMEZONE_CHANGE_INTERVAL_DAYS = 7


async def update_user_settings(
    db: AsyncSession,
    user: User,
    level: str,
    dictionary_code: str,
    tz: str,
    words_per_lesson: int,
    daily_lesson_limit: int,
) -> None:
    """
    Обновляет настройки пользователя.
    
    Raises:
        ValueError: если нарушен лимит смены таймзоны (7 дней).
    """
    # Перезагружаем пользователя в текущей сессии
    stmt = select(User).where(User.id == user.id)
    result = await db.execute(stmt)
    db_user = result.scalar_one()
    
    # Проверка лимита смены таймзоны
    if db_user.timezone != tz and db_user.timezone_changed_at:
        days_since_change = (
            datetime.now(timezone.utc) - db_user.timezone_changed_at
        ).days
        if days_since_change < TIMEZONE_CHANGE_INTERVAL_DAYS:
            remaining = TIMEZONE_CHANGE_INTERVAL_DAYS - days_since_change
            raise ValueError(
                f"Часовой пояс можно менять не чаще раза в 7 дней. "
                f"Осталось {remaining} дн."
            )
    
    # Обновляем поля
    if db_user.timezone != tz:
        db_user.timezone = tz
        db_user.timezone_changed_at = datetime.now(timezone.utc)
    
    db_user.level = level
    db_user.dictionary_code = dictionary_code
    db_user.words_per_lesson = words_per_lesson
    db_user.daily_lesson_limit = daily_lesson_limit
    
    # Событие
    event = Event(user_id=db_user.id, type="settings_updated")
    db.add(event)
    
    await db.commit()
    await db.refresh(db_user)