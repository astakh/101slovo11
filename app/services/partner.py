"""Сервис партнёрской программы."""
import logging
import secrets
import string
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import User
from app.models.partner import Partner
from app.models.partner_invite import PartnerInvite
from app.models.partner_earning import PartnerEarning
from app.models.promo_code import PromoCode
from app.models.event import Event
from app.services.subscription import activate_subscription

logger = logging.getLogger(__name__)

_CODE_ALPHABET = string.ascii_uppercase.replace("O", "").replace("I", "").replace("L", "")
_CODE_ALPHABET += string.digits.replace("0", "").replace("1", "")


def _generate_invite_token() -> str:
    return secrets.token_urlsafe(32)


def _mask_email(email: str) -> str:
    if "@" not in email:
        return email
    local, domain = email.split("@", 1)
    if len(local) <= 1:
        masked_local = local + "***"
    else:
        masked_local = local[0] + "***"
    return f"{masked_local}@{domain}"


# ============================================================
# INVITE MANAGEMENT (админ)
# ============================================================

async def create_partner_invite(db: AsyncSession, admin: User) -> PartnerInvite:
    token = _generate_invite_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.PARTNER_INVITE_TTL_DAYS)

    invite = PartnerInvite(
        token=token,
        created_by=admin.id,
        is_used=False,
        expires_at=expires_at,
    )
    db.add(invite)
    await db.flush()

    event = Event(
        user_id=admin.id,
        type="partner_invite_created",
        payload={"token": token, "expires_at": expires_at.isoformat()},
    )
    db.add(event)
    await db.flush()

    logger.info(f"[PARTNER] Invite created by admin {admin.id}, token={token[:8]}...")
    return invite


async def get_valid_invite(db: AsyncSession, token: str) -> PartnerInvite | None:
    now = datetime.now(timezone.utc)
    stmt = select(PartnerInvite).where(
        PartnerInvite.token == token,
        PartnerInvite.is_used == False,  # noqa: E712
        PartnerInvite.expires_at > now,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_all_invites(db: AsyncSession) -> list[PartnerInvite]:
    stmt = select(PartnerInvite).order_by(PartnerInvite.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ============================================================
# PARTNER REGISTRATION (единая форма)
# ============================================================

async def register_partner_full(
    db: AsyncSession,
    *,
    invite: PartnerInvite,
    email: str | None,
    password: str | None,
    existing_user: User | None,
    name: str,
    partner_type: str,
    inn: str | None = None,
    payout_details: str | None = None,
) -> tuple[User, Partner]:
    """
    Полная регистрация партнёра: создаёт User (если нужно) + Partner.
    Возвращает (user, partner).
    """
    # Определяем пользователя
    if existing_user:
        user = existing_user
    else:
        if not email or not password:
            raise ValueError("Укажите email и пароль")
        # Проверяем уникальность email
        stmt = select(User).where(User.email == email.lower())
        result = await db.execute(stmt)
        if result.scalar_one_or_none():
            raise ValueError("Пользователь с таким email уже существует")
        from app.security import hash_password
        user = User(
            email=email.lower(),
            password_hash=hash_password(password),
            words_per_lesson=settings.WORDS_PER_LESSON_DEFAULT,
            daily_lesson_limit=settings.DAILY_LESSON_LIMIT_DEFAULT,
        )
        db.add(user)
        await db.flush()
        event = Event(user_id=user.id, type="signup")
        db.add(event)

    # Проверяем что пользователь ещё не партнёр
    stmt = select(Partner).where(Partner.user_id == user.id)
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        raise ValueError("Вы уже зарегистрированы как партнёр")

    # Создаём партнёра
    partner = Partner(
        user_id=user.id,
        name=name,
        partner_type=partner_type,
        inn=inn,
        payout_details=payout_details,
        is_active=True,
    )
    db.add(partner)
    await db.flush()

    # Помечаем инвайт как использованный
    invite.is_used = True
    invite.used_by_partner_id = partner.id

    event = Event(
        user_id=user.id,
        type="partner_registered",
        payload={"partner_id": partner.id, "name": name, "partner_type": partner_type},
    )
    db.add(event)
    await db.flush()

    logger.info(f"[PARTNER] User {user.id} registered as partner (id={partner.id})")
    return user, partner


# ============================================================
# PARTNER LOOKUP
# ============================================================

async def get_partner_by_user_id(db: AsyncSession, user_id: int) -> Partner | None:
    stmt = select(Partner).where(Partner.user_id == user_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


# ============================================================
# PROMO CODE MANAGEMENT (партнёр)
# ============================================================

async def propose_partner_promo_code(
    db: AsyncSession,
    partner: Partner,
    code: str,
) -> PromoCode:
    code = code.strip().upper()

    if len(code) < 3 or len(code) > 9:
        raise ValueError("Промокод должен быть от 3 до 9 символов")

    allowed_chars = set(_CODE_ALPHABET)
    if not all(c in allowed_chars for c in code):
        raise ValueError("Промокод может содержать только латинские буквы и цифры (без 0, O, 1, I, L)")

    stmt = select(PromoCode).where(PromoCode.code == code)
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        raise ValueError("Такой промокод уже существует")

    promo = PromoCode(
        code=code,
        owner_user_id=partner.user_id,
        type="partner",
        status="pending",
        is_active=False,
        used_count=0,
    )
    db.add(promo)
    await db.flush()

    event = Event(
        user_id=partner.user_id,
        type="partner_promo_proposed",
        payload={"code": code, "promo_id": promo.id},
    )
    db.add(event)
    await db.flush()

    logger.info(f"[PARTNER] Promo '{code}' proposed by partner {partner.id}, status=pending")
    return promo


async def get_pending_promo_codes(db: AsyncSession) -> list[PromoCode]:
    stmt = (
        select(PromoCode)
        .where(PromoCode.type == "partner", PromoCode.status == "pending")
        .order_by(PromoCode.created_at.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def approve_promo_code(db: AsyncSession, promo_id: int, admin: User) -> None:
    stmt = select(PromoCode).where(PromoCode.id == promo_id)
    result = await db.execute(stmt)
    promo = result.scalar_one_or_none()
    if not promo:
        raise ValueError("Промокод не найден")
    if promo.status != "pending":
        raise ValueError(f"Промокод уже в статусе '{promo.status}'")
    promo.status = "approved"
    promo.is_active = True
    event = Event(user_id=admin.id, type="partner_promo_approved", payload={"promo_id": promo.id, "code": promo.code})
    db.add(event)
    await db.flush()
    logger.info(f"[PARTNER] Promo '{promo.code}' approved by admin {admin.id}")


async def decline_promo_code(db: AsyncSession, promo_id: int, admin: User) -> None:
    stmt = select(PromoCode).where(PromoCode.id == promo_id)
    result = await db.execute(stmt)
    promo = result.scalar_one_or_none()
    if not promo:
        raise ValueError("Промокод не найден")
    promo.status = "disabled"
    promo.is_active = False
    event = Event(user_id=admin.id, type="partner_promo_declined", payload={"promo_id": promo.id, "code": promo.code})
    db.add(event)
    await db.flush()
    logger.info(f"[PARTNER] Promo '{promo.code}' declined by admin {admin.id}")


# ============================================================
# PARTNER DASHBOARD
# ============================================================

async def get_partner_promo(db: AsyncSession, partner_user_id: int) -> PromoCode | None:
    stmt = select(PromoCode).where(
        PromoCode.owner_user_id == partner_user_id,
        PromoCode.type == "partner",
    ).order_by(PromoCode.created_at.desc()).limit(1)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_partner_stats(db: AsyncSession, partner_user_id: int) -> dict:
    """Статистика партнёра — один JOIN вместо N+1."""
    stmt_reg = select(func.count(User.id)).where(User.referred_by_user_id == partner_user_id)
    result_reg = await db.execute(stmt_reg)
    total_registrations = result_reg.scalar_one_or_none() or 0

    # Один JOIN-запрос
    stmt_earnings = (
        select(PartnerEarning, User.email)
        .join(User, PartnerEarning.referred_user_id == User.id)
        .where(PartnerEarning.partner_user_id == partner_user_id)
        .order_by(PartnerEarning.created_at.desc())
    )
    result_earnings = await db.execute(stmt_earnings)
    rows = result_earnings.all()

    total_earnings_kop = 0
    paid_earnings_kop = 0
    pending_earnings_kop = 0
    total_payments = 0
    total_payment_amount_kop = 0
    recent_earnings = []

    for earning, email in rows:
        total_earnings_kop += earning.earning_amount_kop
        total_payments += 1
        total_payment_amount_kop += earning.payment_amount_kop
        if earning.status == "paid":
            paid_earnings_kop += earning.earning_amount_kop
        elif earning.status == "pending":
            pending_earnings_kop += earning.earning_amount_kop

        if len(recent_earnings) < 10:
            recent_earnings.append({
                "id": earning.id,
                "created_at": earning.created_at,
                "user_email_masked": _mask_email(email or ""),
                "payment_amount_kop": earning.payment_amount_kop,
                "commission_percent": earning.commission_percent,
                "earning_amount_kop": earning.earning_amount_kop,
                "status": earning.status,
                "paid_at": earning.paid_at,
            })

    return {
        "total_registrations": total_registrations,
        "total_payments": total_payments,
        "total_payment_amount_kop": total_payment_amount_kop,
        "total_earnings_kop": total_earnings_kop,
        "paid_earnings_kop": paid_earnings_kop,
        "pending_earnings_kop": pending_earnings_kop,
        "recent_earnings": recent_earnings,
    }


# ============================================================
# PARTNER PROFILE
# ============================================================

async def update_partner_profile(
    db: AsyncSession,
    partner: Partner,
    name: str,
    partner_type: str,
    inn: str | None,
    payout_details: str | None,
) -> Partner:
    partner.name = name
    partner.partner_type = partner_type
    partner.inn = inn
    partner.payout_details = payout_details
    await db.flush()
    return partner


# ============================================================
# ADMIN PARTNERS MANAGEMENT
# ============================================================

async def get_all_partners(db: AsyncSession) -> list[dict]:
    stmt = (
        select(Partner, User.email, User)
        .join(User, Partner.user_id == User.id)
        .order_by(Partner.created_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    partners_data = []
    for partner, email, user in rows:
        stmt_balance = select(func.coalesce(func.sum(PartnerEarning.earning_amount_kop), 0)).where(
            PartnerEarning.partner_user_id == partner.user_id,
            PartnerEarning.status == "pending",
        )
        result_balance = await db.execute(stmt_balance)
        pending_balance = result_balance.scalar_one_or_none() or 0

        stmt_reg = select(func.count(User.id)).where(User.referred_by_user_id == partner.user_id)
        result_reg = await db.execute(stmt_reg)
        total_registrations = result_reg.scalar_one_or_none() or 0

        stmt_promo = select(PromoCode).where(
            PromoCode.owner_user_id == partner.user_id,
            PromoCode.type == "partner",
        ).order_by(PromoCode.created_at.desc()).limit(1)
        result_promo = await db.execute(stmt_promo)
        promo = result_promo.scalar_one_or_none()

        partners_data.append({
            "partner": partner,
            "user": user,
            "email": email,
            "pending_balance_kop": pending_balance,
            "total_registrations": total_registrations,
            "promo_code": promo.code if promo else None,
            "promo_status": promo.status if promo else None,
        })

    return partners_data


async def deactivate_partner(db: AsyncSession, partner_id: int, admin: User) -> None:
    stmt = select(Partner).where(Partner.id == partner_id)
    result = await db.execute(stmt)
    partner = result.scalar_one_or_none()
    if not partner:
        raise ValueError("Партнёр не найден")

    partner.is_active = False

    stmt_promo = select(PromoCode).where(
        PromoCode.owner_user_id == partner.user_id,
        PromoCode.type == "partner",
    )
    result_promo = await db.execute(stmt_promo)
    promo = result_promo.scalar_one_or_none()
    if promo:
        promo.is_active = False
        promo.status = "disabled"

    event = Event(
        user_id=admin.id,
        type="partner_deactivated",
        payload={"partner_id": partner.id, "user_id": partner.user_id},
    )
    db.add(event)
    await db.flush()
    logger.info(f"[PARTNER] Partner {partner.id} deactivated by admin {admin.id}")


# ============================================================
# ADMIN EARNINGS
# ============================================================

async def get_partner_earnings(
    db: AsyncSession,
    partner_user_id: int,
    status_filter: str | None = None,
) -> list[dict]:
    stmt = (
        select(PartnerEarning, User.email)
        .join(User, PartnerEarning.referred_user_id == User.id)
        .where(PartnerEarning.partner_user_id == partner_user_id)
        .order_by(PartnerEarning.created_at.desc())
    )
    if status_filter:
        stmt = stmt.where(PartnerEarning.status == status_filter)

    result = await db.execute(stmt)
    rows = result.all()

    earnings = []
    for earning, email in rows:
        earnings.append({
            "earning": earning,
            "user_email_masked": _mask_email(email),
        })
    return earnings


async def mark_earning_as_paid(db: AsyncSession, earning_id: int, admin: User) -> None:
    stmt = select(PartnerEarning).where(PartnerEarning.id == earning_id)
    result = await db.execute(stmt)
    earning = result.scalar_one_or_none()
    if not earning:
        raise ValueError("Начисление не найдено")
    if earning.status != "pending":
        raise ValueError(f"Начисление уже в статусе '{earning.status}'")

    earning.status = "paid"
    earning.paid_at = datetime.now(timezone.utc)

    event = Event(
        user_id=admin.id,
        type="partner_earning_paid",
        payload={"earning_id": earning.id, "partner_user_id": earning.partner_user_id, "amount_kop": earning.earning_amount_kop},
    )
    db.add(event)
    await db.flush()
    logger.info(f"[PARTNER] Earning {earning.id} marked as paid by admin {admin.id}")


# ============================================================
# PARTNER REWARD (вызывается при оплате)
# ============================================================

async def reward_partner_on_purchase(
    db: AsyncSession,
    buyer_user_id: int,
    payment_amount_kop: int,
    payment_id: int,
) -> int | None:
    from app.models.payment import Payment

    buyer_stmt = select(User.referred_by_user_id).where(User.id == buyer_user_id)
    buyer_result = await db.execute(buyer_stmt)
    referrer_user_id = buyer_result.scalar_one_or_none()

    if not referrer_user_id:
        return None

    partner_stmt = select(Partner).where(
        Partner.user_id == referrer_user_id,
        Partner.is_active == True,  # noqa: E712
    )
    partner_result = await db.execute(partner_stmt)
    partner = partner_result.scalar_one_or_none()
    if not partner:
        return None

    # Проверяем что это первая оплата
    payments_stmt = select(func.count(Payment.id)).where(
        Payment.user_id == buyer_user_id,
        Payment.status == "succeeded",
    )
    payments_result = await db.execute(payments_stmt)
    total_payments = payments_result.scalar_one_or_none() or 0

    if total_payments > 1:
        logger.info(f"[PARTNER] Buyer {buyer_user_id} has {total_payments} payments, skipping partner reward")
        return None

    # Идемпотентность
    existing_stmt = select(PartnerEarning).where(
        PartnerEarning.partner_user_id == referrer_user_id,
        PartnerEarning.referred_user_id == buyer_user_id,
    )
    existing_result = await db.execute(existing_stmt)
    if existing_result.scalar_one_or_none():
        logger.warning(f"[PARTNER] Earning already exists for partner {referrer_user_id} and buyer {buyer_user_id}")
        return None

    commission_percent = settings.PARTNER_COMMISSION_PERCENT
    earning_amount_kop = (payment_amount_kop * commission_percent) // 100

    earning = PartnerEarning(
        partner_user_id=referrer_user_id,
        referred_user_id=buyer_user_id,
        payment_id=payment_id,
        payment_amount_kop=payment_amount_kop,
        commission_percent=commission_percent,
        earning_amount_kop=earning_amount_kop,
        status="pending",
    )
    db.add(earning)

    bonus_days = settings.PARTNER_BONUS_DAYS
    if bonus_days > 0:
        await activate_subscription(
            db, user_id=buyer_user_id, plan="referral_bonus", source="referral", extra_days=bonus_days,
        )

    event_partner = Event(
        user_id=referrer_user_id,
        type="partner_earning_created",
        payload={"buyer_user_id": buyer_user_id, "earning_amount_kop": earning_amount_kop},
    )
    db.add(event_partner)

    event_buyer = Event(
        user_id=buyer_user_id,
        type="partner_bonus_received",
        payload={"partner_user_id": referrer_user_id, "bonus_days": bonus_days},
    )
    db.add(event_buyer)

    await db.flush()

    logger.info(
        f"[PARTNER] Reward: partner {referrer_user_id} gets {earning_amount_kop} kop, "
        f"buyer {buyer_user_id} gets +{bonus_days} days"
    )
    return referrer_user_id