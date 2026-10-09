"""Сервис подписок: проверка, активация, истечение."""
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.models.user import User
from app.models.subscription import Subscription
from app.models.payment import Payment
from app.models.event import Event

logger = logging.getLogger(__name__)

# Длительность подписок в днях
PLAN_DAYS = {
    "monthly": 30,
    "six_months": 180,
}


async def get_active_subscription(db: AsyncSession, user_id: int) -> Subscription | None:
    """Возвращает активную подписку пользователя или None."""
    now = datetime.now(timezone.utc)
    stmt = (
        select(Subscription)
        .where(
            Subscription.user_id == user_id,
            Subscription.status == "active",
            Subscription.expires_at > now,
        )
        .order_by(Subscription.expires_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def is_premium(db: AsyncSession, user_id: int) -> bool:
    """Проверяет, есть ли у пользователя активная подписка."""
    sub = await get_active_subscription(db, user_id)
    return sub is not None


async def get_subscription_status(db: AsyncSession, user_id: int) -> dict:
    """
    Возвращает полную информацию о подписке для шаблонов.

    Returns:
        {
            "is_premium": bool,
            "plan": str | None,
            "expires_at": datetime | None,
            "days_left": int,
            "source": str | None,
        }
    """
    sub = await get_active_subscription(db, user_id)
    if not sub:
        return {
            "is_premium": False,
            "plan": None,
            "expires_at": None,
            "days_left": 0,
            "source": None,
        }

    now = datetime.now(timezone.utc)
    days_left = max((sub.expires_at - now).days, 0)

    return {
        "is_premium": True,
        "plan": sub.plan,
        "expires_at": sub.expires_at,
        "days_left": days_left,
        "source": sub.source,
    }


async def activate_subscription(
    db: AsyncSession,
    user_id: int,
    plan: str,
    source: str = "payment",
    payment_id: int | None = None,
    extra_days: int = 0,
) -> Subscription:
    """
    Активирует подписку.
    Если уже есть активная — продлевает её.

    Args:
        plan: "monthly" | "six_months" | "referral_bonus"
        source: "payment" | "referral"
        payment_id: ID платежа (для оплаты)
        extra_days: дополнительные дни (для рефералки)
    """
    now = datetime.now(timezone.utc)
    base_days = PLAN_DAYS.get(plan, 30)
    total_days = base_days + extra_days

    # Проверяем, есть ли уже активная подписка
    existing = await get_active_subscription(db, user_id)

    if existing:
        # Продлеваем: добавляем дни к текущему expires_at
        existing.expires_at = existing.expires_at + timedelta(days=total_days)
        # Обновляем план только если это НЕ реферальный бонус
        # (чтобы не перезаписать "monthly" на "referral_bonus")
        if source != "referral":
            existing.plan = plan
        if payment_id:
            existing.payment_id = payment_id

        event = Event(
            user_id=user_id,
            type="subscription_extended",
            payload={
                "subscription_id": existing.id,
                "plan": plan,
                "source": source,
                "added_days": total_days,
                "new_expires_at": existing.expires_at.isoformat(),
            },
        )
        db.add(event)
        await db.flush()

        logger.info(
            f"[SUBSCRIPTION] Extended for user_id={user_id}, "
            f"plan={plan}, source={source}, +{total_days} days, "
            f"expires={existing.expires_at}"
        )
        return existing

    # Создаём новую подписку
    expires_at = now + timedelta(days=total_days)

    sub = Subscription(
        user_id=user_id,
        plan=plan,
        status="active",
        source=source,
        payment_id=payment_id,
        started_at=now,
        expires_at=expires_at,
    )
    db.add(sub)
    await db.flush()

    event = Event(
        user_id=user_id,
        type="subscription_activated",
        payload={
            "subscription_id": sub.id,
            "plan": plan,
            "source": source,
            "days": total_days,
            "expires_at": expires_at.isoformat(),
        },
    )
    db.add(event)
    await db.flush()

    logger.info(
        f"[SUBSCRIPTION] Activated for user_id={user_id}, "
        f"plan={plan}, source={source}, expires={expires_at}"
    )
    return sub


async def cancel_subscription(db: AsyncSession, user_id: int) -> bool:
    """
    Отменяет подписку (доступ сохраняется до expires_at).
    Возвращает True если подписка была найдена и отменена.
    """
    sub = await get_active_subscription(db, user_id)
    if not sub:
        return False

    sub.status = "canceled"
    sub.canceled_at = datetime.now(timezone.utc)

    event = Event(
        user_id=user_id,
        type="subscription_canceled",
        payload={"subscription_id": sub.id},
    )
    db.add(event)
    await db.flush()

    logger.info(f"[SUBSCRIPTION] Canceled for user_id={user_id}, sub_id={sub.id}")
    return True


async def expire_subscriptions(db: AsyncSession) -> int:
    """
    Фоновая задача: переводит истёкшие подписки в статус 'expired'.
    Вызывается периодически (например, каждый час).

    Returns:
        Количество переведённых подписок.
    """
    now = datetime.now(timezone.utc)
    stmt = (
        update(Subscription)
        .where(
            Subscription.status == "active",
            Subscription.expires_at <= now,
        )
        .values(status="expired")
    )
    result = await db.execute(stmt)
    count = result.rowcount

    if count > 0:
        logger.info(f"[SUBSCRIPTION] Expired {count} subscriptions")

    return count


def get_plan_price_kop(plan: str) -> int:
    """Возвращает цену плана в копейках."""
    if plan == "monthly":
        return settings.SUBSCRIPTION_MONTHLY_PRICE_KOP
    elif plan == "six_months":
        return settings.SUBSCRIPTION_6M_PRICE_KOP
    return 0


def get_plan_label(plan: str) -> str:
    """Человекочитаемое название плана."""
    labels = {
        "monthly": "Месячная подписка",
        "six_months": "Подписка на 6 месяцев",
        "referral_bonus": "Бонус по реферальной программе",
    }
    return labels.get(plan, plan)