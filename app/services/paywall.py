"""Сервис проверки лимитов для Freemium / Premium."""
import logging
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.models.user import User
from app.models.lesson import Lesson
from app.models.subscription import Subscription
from app.services.subscription import is_premium

logger = logging.getLogger(__name__)


async def get_total_lessons_count(db: AsyncSession, user_id: int) -> int:
    """Возвращает общее количество уроков пользователя (все статусы)."""
    stmt = select(func.count(Lesson.id)).where(Lesson.user_id == user_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none() or 0


async def check_lesson_access(db: AsyncSession, user: User) -> dict:
    """
    Проверяет, может ли пользователь начать новый урок.

    Возвращает:
    {
        "allowed": bool,
        "reason": str | None,  # причина запрета
        "is_premium": bool,
        "total_lessons": int,
        "free_lessons_remaining": int | None,  # только для freemium
    }
    """
    premium = await is_premium(db, user.id)

    # Для Premium — общий лимит не применяется
    if premium:
        return {
            "allowed": True,
            "reason": None,
            "is_premium": True,
            "total_lessons": await get_total_lessons_count(db, user.id),
            "free_lessons_remaining": None,
        }

    # Для Freemium — проверяем общий лимит уроков
    total = await get_total_lessons_count(db, user.id)
    remaining = settings.FREE_LESSONS_TOTAL_LIMIT - total

    if total >= settings.FREE_LESSONS_TOTAL_LIMIT:
        return {
            "allowed": False,
            "reason": "free_limit_reached",
            "is_premium": False,
            "total_lessons": total,
            "free_lessons_remaining": 0,
        }

    return {
        "allowed": True,
        "reason": None,
        "is_premium": False,
        "total_lessons": total,
        "free_lessons_remaining": remaining,
    }


def get_effective_daily_limit(user: User) -> int:
    """
    Возвращает дневной лимит уроков пользователя.

    Единый для всех тарифов. Берётся из user.daily_lesson_limit,
    что позволяет администратору назначать особые условия
    отдельным пользователям.
    """
    return user.daily_lesson_limit


async def get_paywall_context(db: AsyncSession, user: User) -> dict:
    """
    Контекст для отображения пейволла / информации о подписке в шаблонах.
    Используется в дашборде, превью урока, настройках.
    """
    access = await check_lesson_access(db, user)

    return {
        "is_premium": access["is_premium"],
        "free_lessons_remaining": access.get("free_lessons_remaining"),
        "free_lessons_total": settings.FREE_LESSONS_TOTAL_LIMIT,
        "max_lessons_per_day": settings.MAX_LESSONS_PER_DAY,
        "effective_daily_limit": get_effective_daily_limit(user),
        "paywall_triggered": not access["allowed"],
        "paywall_reason": access.get("reason"),
    }