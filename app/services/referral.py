"""Сервис реферальной программы (обычные юзеры + партнёры)."""
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

_CODE_ALPHABET = string.ascii_uppercase.replace("O", "").replace("I", "").replace("L", "")
_CODE_ALPHABET += string.digits.replace("0", "").replace("1", "")
_CODE_LENGTH = 9


def _generate_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))


async def get_or_create_promo_code(db: AsyncSession, user_id: int) -> PromoCode:
    stmt = select(PromoCode).where(
        PromoCode.owner_user_id == user_id,
        PromoCode.type == "user_referral",
        PromoCode.is_active == True,  # noqa: E712
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing:
        return existing

    for _ in range(10):
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
        status="approved",
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
    code = code.strip().upper()

    if user.promo_code_attempts >= settings.REFERRAL_PROMO_MAX_ATTEMPTS:
        return False, "Лимит попыток ввода промокода исчерпан"

    user.promo_code_attempts += 1

    stmt_own = select(PromoCode).where(
        PromoCode.owner_user_id == user.id,
        PromoCode.code == code,
    )
    result_own = await db.execute(stmt_own)
    if result_own.scalar_one_or_none():
        return False, "Нельзя использовать свой промокод"

    stmt = select(PromoCode).where(
        PromoCode.code == code,
        PromoCode.is_active == True,  # noqa: E712
        PromoCode.status == "approved",
        PromoCode.type.in_(["user_referral", "partner"]),
    )
    result = await db.execute(stmt)
    promo = result.scalar_one_or_none()
    if not promo:
        return False, "Промокод не найден или не активен"

    if user.referred_by_user_id is not None:
        return False, "Промокод уже был применён"

    # Для партнёрского промокода проверяем что партнёр активен
    if promo.type == "partner":
        from app.models.partner import Partner
        partner_stmt = select(Partner).where(
            Partner.user_id == promo.owner_user_id,
            Partner.is_active == True,  # noqa: E712
        )
        partner_result = await db.execute(partner_stmt)
        if not partner_result.scalar_one_or_none():
            return False, "Промокод недействителен"

    user.referred_by_user_id = promo.owner_user_id

    if promo.type == "user_referral":
        referral = Referral(
            referrer_user_id=promo.owner_user_id,
            referred_user_id=user.id,
            promo_code_id=promo.id,
            status="pending",
        )
        db.add(referral)

    promo.used_count += 1

    event = Event(
        user_id=user.id,
        type="promo_code_applied",
        payload={"code": code, "type": promo.type, "owner_user_id": promo.owner_user_id},
    )
    db.add(event)
    await db.flush()

    if promo.type == "partner":
        logger.info(f"[PARTNER] Partner promo '{code}' applied: user_id={user.id} referred by {promo.owner_user_id}")
        return True, "Промокод применён! Вы получите бонусные дни после первой оплаты."
    else:
        logger.info(f"[REFERRAL] Code '{code}' applied: user_id={user.id} referred by {promo.owner_user_id}")
        return True, "Промокод применён! Вы и ваш друг получите бонус после вашей подписки."


async def reward_referrer_on_purchase(
    db: AsyncSession,
    buyer_user_id: int,
    payment_amount_kop: int | None = None,
    payment_id: int | None = None,
) -> int | None:
    buyer_stmt = select(User.referred_by_user_id).where(User.id == buyer_user_id)
    buyer_result = await db.execute(buyer_stmt)
    referrer_user_id = buyer_result.scalar_one_or_none()

    if not referrer_user_id:
        return None

    from app.models.partner import Partner
    partner_stmt = select(Partner).where(Partner.user_id == referrer_user_id)
    partner_result = await db.execute(partner_stmt)
    partner = partner_result.scalar_one_or_none()

    if partner:
        # ПАРТНЁР
        if payment_amount_kop and payment_id:
            from app.services.partner import reward_partner_on_purchase
            await reward_partner_on_purchase(db, buyer_user_id, payment_amount_kop, payment_id)
        return referrer_user_id
    else:
        # ОБЫЧНЫЙ РЕФЕРЕР
        stmt = select(Referral).where(
            Referral.referred_user_id == buyer_user_id,
            Referral.status == "pending",
        )
        result = await db.execute(stmt)
        referral = result.scalar_one_or_none()
        if not referral:
            return None

        bonus_days = settings.REFERRAL_BONUS_DAYS

        await activate_subscription(db, user_id=referral.referrer_user_id, plan="referral_bonus", source="referral", extra_days=bonus_days)
        await activate_subscription(db, user_id=buyer_user_id, plan="referral_bonus", source="referral", extra_days=bonus_days)

        referral.status = "rewarded"
        referral.rewarded_at = datetime.now(timezone.utc)

        event = Event(user_id=referral.referrer_user_id, type="referral_reward_granted", payload={"referred_user_id": buyer_user_id, "bonus_days": bonus_days})
        db.add(event)
        event2 = Event(user_id=buyer_user_id, type="referral_bonus_received", payload={"referrer_user_id": referral.referrer_user_id, "bonus_days": bonus_days})
        db.add(event2)
        await db.flush()

        logger.info(f"[REFERRAL] Rewards granted: referrer {referral.referrer_user_id} and buyer {buyer_user_id} get +{bonus_days} days")
        return referral.referrer_user_id


async def get_referral_stats(db: AsyncSession, user_id: int) -> dict:
    promo = await get_or_create_promo_code(db, user_id)

    stmt_total = select(func.count(Referral.id)).where(Referral.referrer_user_id == user_id)
    result_total = await db.execute(stmt_total)
    total_invited = result_total.scalar_one_or_none() or 0

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