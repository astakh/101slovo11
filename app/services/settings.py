"""Сервис для обновления настроек пользователя."""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.user import User
from app.models.event import Event

async def update_user_settings(
    db: AsyncSession,
    user: User,
    level: str,
    dictionary_code: str,
    words_per_lesson: int,
) -> None:
    """
    Обновляет настройки пользователя.
    Часовой пояс больше не изменяется (всегда Europe/Moscow).
    daily_lesson_limit не изменяется через настройки пользователя.
    """
    # Перезагружаем пользователя в текущей сессии
    stmt = select(User).where(User.id == user.id)
    result = await db.execute(stmt)
    db_user = result.scalar_one()

    # Обновляем поля (кроме timezone и daily_lesson_limit)
    db_user.level = level
    db_user.dictionary_code = dictionary_code
    db_user.words_per_lesson = words_per_lesson

    # Событие
    event = Event(user_id=db_user.id, type="settings_updated")
    db.add(event)
    await db.commit()
    await db.refresh(db_user)