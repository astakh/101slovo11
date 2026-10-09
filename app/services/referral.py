"""Сервис реферальной программы."""
import logging
import secrets
import string
from datetime import datetime, timezone
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.models.user import User
from app.models.promo_code import PromoCode
from app.models.referral import Referral
from app.models.event import Event
from app.services.subscription import activate_subscription

logger = logging.getLogger(__name__)

# Алфавит для промокодов (без 0, O, 1, I, L для читаемости)
_CODE_ALPHABET = string.ascii_uppercase.replace("O", "").replace("I", "").replace("L", "")
_CODE_ALPHABET += string.digits.replace("0", "").replace("1", "")
_CODE_LENGTH = 6


def _generate_code() -> str:
    """Генерирует случайный промокод из 6 символов."""
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))


async def get_or_create_promo_code(db: AsyncSession, user_id: int) -> PromoCode:
    """
    Возвращает промокод пользователя или создаёт новый.
    """
    # Ищем существующий
    stmt = select(PromoCode).where(
        PromoCode.owner_user_id == user_id,
        PromoCode.type == "user_referral",
        PromoCode.is_active == True,
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing:
        return existing

    # Генерируем уникальный код
    for _ in range(10):  # Максимум 10 попыток
        code = _generate_code()
        stmt_check = select(PromoCode).where(PromoCode.code == code)
        result_check = await db.execute(stmt_check)
        if result_check.scalar_one_or_none() is None:
            break
    else:
        raise RuntimeError("Не удалось сгенерировать уникальный промокод")

    promo = PromoCode(
        code=code,
        owner_user_id=user_id,
        type="user_referral",
        is_active=True,
        used_count=0,
    )
    db.add(promo)
    await db.flush()

    logger.info(f"[REFERRAL] Created promo code '{code}' for user_id={user_id}")
    return promo


async def apply_referral_code(
    db: AsyncSession,
    user: User,
    code: str,
) -> tuple[bool, str]:
    """
    Применяет реферальный код к пользователю при регистрации.

    Возвращает:
        (success: bool, message: str)
    """
    code = code.strip().upper()

    # Проверка лимита попыток
    if user.promo_code_attempts >= settings.REFERRAL_PROMO_MAX_ATTEMPTS:
        return False, "Лимит попыток ввода промокода исчерпан"

    # Увеличиваем счётчик попыток
    user.promo_code_attempts += 1

    # Проверка: нельзя использовать свой код
    stmt_own = select(PromoCode).where(
        PromoCode.owner_user_id == user.id,
        PromoCode.code == code,
    )
    result_own = await db.execute(stmt_own)
    if result_own.scalar_one_or_none():
        return False, "Нельзя использовать свой промокод"

    # Ищем промокод
    stmt = select(PromoCode).where(
        PromoCode.code == code,
        PromoCode.is_active == True,
        PromoCode.type == "user_referral",
    )
    result = await db.execute(stmt)
    promo = result.scalar_one_or_none()

    if not promo:
        return False, "Промокод не найден"

    # Проверка: пользователь ещё не привязан к рефереру
    if user.referred_by_user_id is not None:
        return False, "Промокод уже был применён"

    # Привязываем
    user.referred_by_user_id = promo.owner_user_id

    # Создаём запись в referrals
    referral = Referral(
        referrer_user_id=promo.owner_user_id,
        referred_user_id=user.id,
        promo_code_id=promo.id,
        status="pending",
    )
    db.add(referral)

    # Увеличиваем счётчик использований промокода
    promo.used_count += 1

    event = Event(
        user_id=user.id,
        type="referral_code_applied",
        payload={"code": code, "referrer_user_id": promo.owner_user_id},
    )
    db.add(event)
    await db.flush()

    logger.info(
        f"[REFERRAL] Code '{code}' applied: "
        f"user_id={user.id} referred by user_id={promo.owner_user_id}"
    )
    return True, "Промокод применён! Ваш друг получит бонус после вашей подписки."


async def reward_referrer_on_purchase(
    db: AsyncSession,
    buyer_user_id: int,
) -> int | None:
    """
    Начисляет бонус рефереру после покупки подписки.
    Вызывается после успешной оплаты.

    Возвращает:
        user_id реферера или None если реферала нет.
    """
    # Ищем pending-реферал для этого пользователя
    stmt = select(Referral).where(
        Referral.referred_user_id == buyer_user_id,
        Referral.status == "pending",
    )
    result = await db.execute(stmt)
    referral = result.scalar_one_or_none()

    if not referral:
        return None

    # Начисляем бонус рефереру
    bonus_days = settings.REFERRAL_BONUS_DAYS

    await activate_subscription(
        db,
        user_id=referral.referrer_user_id,
        plan="referral_bonus",
        source="referral",
        extra_days=bonus_days,
    )

    # Обновляем реферал
    referral.status = "rewarded"
    referral.rewarded_at = datetime.now(timezone.utc)

    event = Event(
        user_id=referral.referrer_user_id,
        type="referral_reward_granted",
        payload={
            "referred_user_id": buyer_user_id,
            "bonus_days": bonus_days,
        },
    )
    db.add(event)

    event2 = Event(
        user_id=buyer_user_id,
        type="referral_reward_given",
        payload={
            "referrer_user_id": referral.referrer_user_id,
            "bonus_days": bonus_days,
        },
    )
    db.add(event2)
    await db.flush()

    logger.info(
        f"[REFERRAL] Reward granted: user_id={referral.referrer_user_id} "
        f"gets +{bonus_days} days for referring user_id={buyer_user_id}"
    )
    return referral.referrer_user_id


async def get_referral_stats(db: AsyncSession, user_id: int) -> dict:
    """
    Статистика рефералов для личного кабинета.

    Returns:
        {
            "promo_code": str,
            "total_invited": int,
            "total_rewarded": int,
            "total_bonus_days": int,
        }
    """
    promo = await get_or_create_promo_code(db, user_id)

    # Считаем приглашённых
    stmt_total = select(func.count(Referral.id)).where(
        Referral.referrer_user_id == user_id,
    )
    result_total = await db.execute(stmt_total)
    total_invited = result_total.scalar_one_or_none() or 0

    # Считаем награждённых
    stmt_rewarded = select(func.count(Referral.id)).where(
        Referral.referrer_user_id == user_id,
        Referral.status == "rewarded",
    )
    result_rewarded = await db.execute(stmt_rewarded)
    total_rewarded = result_rewarded.scalar_one_or_none() or 0

    return {
        "promo_code": promo.code,
        "total_invited": total_invited,
        "total_rewarded": total_rewarded,
        "total_bonus_days": total_rewarded * settings.REFERRAL_BONUS_DAYS,
    }