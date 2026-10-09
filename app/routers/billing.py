"""Роуты биллинга и управления подпиской."""
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Depends, Form, HTTPException, status
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db import get_db
from app.deps import require_auth, require_csrf
from app.core.templates import templates
from app.models.user import User
from app.models.payment import Payment
from app.config import settings
from app.services.subscription import (
    get_subscription_status,
    activate_subscription,
    cancel_subscription,
    get_plan_price_kop,
    get_plan_label,
)
from app.services.referral import get_referral_stats, reward_referrer_on_purchase
from app.services.yookassa_client import (
    create_payment,
    get_payment_info,
    is_webhook_ip_allowed,
    YooKassaError,
)
from app.models.event import Event
from app.utils.flash import add_flash

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])


def _parse_yookassa_datetime(value) -> datetime | None:
    """
    Парсит дату/время из ответа ЮKassa.
    ЮKassa возвращает ISO-строки вида '2026-10-09T08:21:23.123Z'.
    Возвращает datetime с timezone или None.
    """
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            iso_str = value.replace("Z", "+00:00")
            return datetime.fromisoformat(iso_str)
        except (ValueError, TypeError) as e:
            logger.warning(f"[BILLING] Failed to parse datetime '{value}': {e}")
            return None
    return None


@router.get("")
async def billing_page(
    request: Request,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Страница управления подпиской."""
    if not user.is_onboarded:
        return RedirectResponse(url="/onboarding", status_code=status.HTTP_303_SEE_OTHER)

    sub_status = await get_subscription_status(db, user.id)
    referral_stats = await get_referral_stats(db, user.id)

    return templates.TemplateResponse(
        "billing/manage.html",
        {
            "request": request,
            "user": user,
            "subscription": sub_status,
            "referral": referral_stats,
        },
    )


@router.get("/plans")
async def plans_page(
    request: Request,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Страница выбора тарифа."""
    if not user.is_onboarded:
        return RedirectResponse(url="/onboarding", status_code=status.HTTP_303_SEE_OTHER)

    sub_status = await get_subscription_status(db, user.id)

    monthly_price = settings.SUBSCRIPTION_MONTHLY_PRICE_KOP / 100
    six_month_price = settings.SUBSCRIPTION_6M_PRICE_KOP / 100
    six_month_per_month = six_month_price / 6
    six_month_full = monthly_price * 6
    six_month_saving = six_month_full - six_month_price

    return templates.TemplateResponse(
        "billing/plans.html",
        {
            "request": request,
            "user": user,
            "subscription": sub_status,
            "monthly_price": monthly_price,
            "six_month_price": six_month_price,
            "six_month_per_month": six_month_per_month,
            "six_month_full": six_month_full,
            "six_month_saving": six_month_saving,
            "discount_percent": settings.SUBSCRIPTION_6M_DISCOUNT_PERCENT,
        },
    )


@router.post("/subscribe", dependencies=[Depends(require_csrf)])
async def subscribe_post(
    request: Request,
    plan: str = Form(...),
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Инициация подписки.
    Создаёт платёж в ЮKassa и редиректит на оплату.
    """
    if plan not in ("monthly", "six_months"):
        raise HTTPException(status_code=400, detail="Неизвестный тариф")

    if not user.is_onboarded:
        return RedirectResponse(url="/onboarding", status_code=status.HTTP_303_SEE_OTHER)

    # Создаём запись платежа в БД (статус pending)
    price_kop = get_plan_price_kop(plan)
    payment = Payment(
        user_id=user.id,
        plan=plan,
        amount_kop=price_kop,
        status="pending",
        description=f"Подписка: {get_plan_label(plan)}",
    )
    db.add(payment)
    await db.flush()  # получаем payment.id

    # Проверяем, настроена ли ЮKassa
    if not settings.YOOKASSA_SHOP_ID or not settings.YOOKASSA_SECRET_KEY:
        # DEV-режим: сразу активируем подписку
        logger.warning("[BILLING] ЮKassa не настроена — DEV-режим: активируем подписку")
        payment.status = "succeeded"
        payment.paid_at = datetime.now(timezone.utc)
        await activate_subscription(
            db,
            user_id=user.id,
            plan=plan,
            source="payment",
            payment_id=payment.id,
        )
        # В DEV-режиме начисляем бонус здесь (нет webhook)
        await reward_referrer_on_purchase(db, user.id)

        response = RedirectResponse(url="/billing", status_code=status.HTTP_303_SEE_OTHER)
        add_flash(response, "success", "Подписка активирована (DEV-режим) 🎉")
        return response

    # PROD-режим: создаём платёж в ЮKassa
    try:
        # return_url — куда вернётся пользователь после оплаты
        base_url = str(request.base_url).rstrip("/")
        return_url = f"{base_url}/billing/success?payment_id={payment.id}"

        result = await create_payment(payment, return_url)

        # Сохраняем yookassa_payment_id
        payment.yookassa_payment_id = result["yookassa_payment_id"]
        await db.flush()

        # Редиректим на страницу оплаты
        logger.info(
            f"[BILLING] Redirecting to ЮKassa | user_id={user.id} | "
            f"payment_id={payment.id} | yookassa_id={result['yookassa_payment_id']}"
        )
        return RedirectResponse(
            url=result["confirmation_url"],
            status_code=status.HTTP_303_SEE_OTHER,
        )

    except YooKassaError as e:
        logger.error(f"[BILLING] YooKassa error: {e}")
        # Помечаем платёж как failed
        payment.status = "failed"
        await db.flush()

        response = RedirectResponse(url="/billing/plans", status_code=status.HTTP_303_SEE_OTHER)
        add_flash(response, "error", f"Ошибка создания платежа: {e}")
        return response


@router.get("/success")
async def billing_success(
    request: Request,
    payment_id: int | None = None,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Страница успеха после оплаты (return_url от ЮKassa).
    Проверяет статус платежа и активирует подписку если нужно.
    
    ВАЖНО: Бонус рефереру начисляется ТОЛЬКО через webhook,
    чтобы избежать двойного начисления.
    """
    if not user.is_onboarded:
        return RedirectResponse(url="/onboarding", status_code=status.HTTP_303_SEE_OTHER)

    if not payment_id:
        return RedirectResponse(url="/billing", status_code=status.HTTP_303_SEE_OTHER)

    # Загружаем платёж
    stmt = select(Payment).where(
        Payment.id == payment_id,
        Payment.user_id == user.id,
    )
    result = await db.execute(stmt)
    payment = result.scalar_one_or_none()

    if not payment:
        return RedirectResponse(url="/billing", status_code=status.HTTP_303_SEE_OTHER)

    # Если уже оплачен — просто идём на /billing
    if payment.status == "succeeded":
        return RedirectResponse(url="/billing", status_code=status.HTTP_303_SEE_OTHER)

    # Если ЮKassa настроена — проверяем статус через API
    if settings.YOOKASSA_SHOP_ID and settings.YOOKASSA_SECRET_KEY and payment.yookassa_payment_id:
        try:
            info = await get_payment_info(payment.yookassa_payment_id)
            yookassa_status = info.get("status", "")

            if yookassa_status == "succeeded":
                payment.status = "succeeded"
                paid_at_raw = info.get("captured_at") or info.get("created_at")
                payment.paid_at = _parse_yookassa_datetime(paid_at_raw)

                await activate_subscription(
                    db,
                    user_id=user.id,
                    plan=payment.plan,
                    source="payment",
                    payment_id=payment.id,
                )
                # ❌ НЕ вызываем reward_referrer_on_purchase здесь!
                # Webhook придёт и начислит бонус.
                logger.info(
                    f"[BILLING] Payment succeeded (via API check) | "
                    f"payment_id={payment.id} | user_id={user.id}"
                )
            elif yookassa_status == "canceled":
                payment.status = "failed"
                logger.info(f"[BILLING] Payment canceled | payment_id={payment.id}")
            # pending — ждём webhook

        except YooKassaError as e:
            logger.warning(f"[BILLING] Could not check payment status: {e}")

    response = RedirectResponse(url="/billing", status_code=status.HTTP_303_SEE_OTHER)
    if payment.status == "succeeded":
        add_flash(response, "success", "Оплата прошла успешно! Подписка активирована 🎉")
    elif payment.status == "failed":
        add_flash(response, "error", "Оплата не прошла. Попробуйте ещё раз.")
    else:
        add_flash(response, "info", "Оплата обрабатывается. Подписка активируется автоматически.")

    return response


@router.post("/cancel", dependencies=[Depends(require_csrf)])
async def cancel_post(
    request: Request,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Отмена подписки."""
    success = await cancel_subscription(db, user.id)

    response = RedirectResponse(url="/billing", status_code=status.HTTP_303_SEE_OTHER)
    if success:
        add_flash(response, "info", "Подписка отменена. Доступ сохранится до конца оплаченного периода.")
    else:
        add_flash(response, "error", "Активная подписка не найдена.")

    return response


# ============================================================
# WEBHOOK от ЮKassa
# ============================================================

@router.post("/webhook")
async def billing_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Webhook-эндпоинт для уведомлений от ЮKassa.

    Обрабатывает события:
    - payment.succeeded — платёж успешен
    - payment.canceled — платёж отменён

    Защита: проверка IP-адреса отправителя.
    
    ВАЖНО: Бонус рефереру начисляется ТОЛЬКО здесь,
    чтобы избежать двойного начисления.
    """
    # 1. Проверка IP
    client_ip = request.client.host if request.client else ""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()

    if not is_webhook_ip_allowed(client_ip):
        logger.warning(f"[WEBHOOK] Rejected: IP {client_ip} not in ЮKassa whitelist")
        return JSONResponse(
            {"error": "Forbidden"},
            status_code=403,
        )

    # 2. Парсим тело
    try:
        body = await request.json()
    except Exception:
        logger.error("[WEBHOOK] Invalid JSON body")
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    event = body.get("event", "")
    obj = body.get("object", {})
    yookassa_payment_id = obj.get("id", "")

    logger.info(f"[WEBHOOK] Received event: {event} | yookassa_id={yookassa_payment_id}")

    # 3. Находим платёж в БД
    if not yookassa_payment_id:
        logger.warning("[WEBHOOK] No payment id in notification")
        return JSONResponse({"status": "ok"})

    stmt = select(Payment).where(Payment.yookassa_payment_id == yookassa_payment_id)
    result = await db.execute(stmt)
    payment = result.scalar_one_or_none()

    if not payment:
        logger.warning(
            f"[WEBHOOK] Payment not found in DB | yookassa_id={yookassa_payment_id}"
        )
        return JSONResponse({"status": "ok"})

    # 4. Обрабатываем событие
    if event == "payment.succeeded":
        if payment.status != "succeeded":
            payment.status = "succeeded"
            paid_at_raw = obj.get("captured_at") or obj.get("created_at")
            payment.paid_at = _parse_yookassa_datetime(paid_at_raw)

            await activate_subscription(
                db,
                user_id=payment.user_id,
                plan=payment.plan,
                source="payment",
                payment_id=payment.id,
            )

            # ✅ Начисляем бонус рефереру ТОЛЬКО здесь
            await reward_referrer_on_purchase(db, payment.user_id)

            logger.info(
                f"[WEBHOOK] Payment succeeded | payment_id={payment.id} | "
                f"user_id={payment.user_id} | plan={payment.plan}"
            )

            event_record = Event(
                user_id=payment.user_id,
                type="payment_succeeded",
                payload={
                    "payment_id": payment.id,
                    "yookassa_payment_id": yookassa_payment_id,
                    "plan": payment.plan,
                    "amount_kop": payment.amount_kop,
                },
            )
            db.add(event_record)

    elif event == "payment.canceled":
        if payment.status not in ("succeeded", "failed"):
            payment.status = "failed"

            logger.info(
                f"[WEBHOOK] Payment canceled | payment_id={payment.id} | "
                f"user_id={payment.user_id}"
            )

            event_record = Event(
                user_id=payment.user_id,
                type="payment_canceled",
                payload={
                    "payment_id": payment.id,
                    "yookassa_payment_id": yookassa_payment_id,
                    "reason": obj.get("cancellation_details", {}).get("reason", "unknown"),
                },
            )
            db.add(event_record)

    else:
        logger.info(f"[WEBHOOK] Unhandled event: {event}")

    # 5. Всегда возвращаем 200
    return JSONResponse({"status": "ok"})