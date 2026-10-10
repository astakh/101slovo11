"""Роуты партнёрской программы."""
import logging
from fastapi import APIRouter, Request, Depends, Form, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_auth, require_csrf
from app.core.templates import templates
from app.models.user import User
from app.config import settings
from app.utils.flash import add_flash
from app.services.auth import create_session
from app.services.partner import (
    get_valid_invite,
    register_partner_full,
    get_partner_by_user_id,
    get_partner_promo,
    get_partner_stats,
    propose_partner_promo_code,
    update_partner_profile,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/partner", tags=["partner"])

VALID_PARTNER_TYPES = ("self_employed", "individual", "company")


@router.get("/register")
async def partner_register_page(
    request: Request,
    invite: str = "",
    db: AsyncSession = Depends(get_db),
):
    """Страница регистрации партнёра по инвайт-ссылке. Единая форма."""
    # Если уже партнёр — редирект в кабинет
    if request.state.user:
        partner = await get_partner_by_user_id(db, request.state.user.id)
        if partner:
            return RedirectResponse(url="/partner/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    # Проверяем инвайт
    valid_invite = None
    invite_error = None
    if invite:
        valid_invite = await get_valid_invite(db, invite)
        if not valid_invite:
            invite_error = "Ссылка недействительна или истекла"
    else:
        invite_error = "Отсутствует параметр приглашения"

    return templates.TemplateResponse(
        "partner/register.html",
        {
            "request": request,
            "invite_token": invite,
            "valid_invite": valid_invite,
            "invite_error": invite_error,
        },
    )


@router.post("/register")
async def partner_register_post(
    request: Request,
    invite: str = Form(...),
    # Данные аккаунта (если не залогинен)
    email: str = Form(default=""),
    password: str = Form(default=""),
    password_confirm: str = Form(default=""),
    # Данные партнёра
    name: str = Form(...),
    partner_type: str = Form(...),
    inn: str = Form(default=""),
    payout_details: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    """Обработка регистрации партнёра. Создаёт User + Partner за один шаг."""
    # Валидация инвайта
    valid_invite = await get_valid_invite(db, invite)
    if not valid_invite:
        return _render_register_error(request, invite, "Ссылка недействительна или истекла")

    # Валидация типа партнёра
    if partner_type not in VALID_PARTNER_TYPES:
        return _render_register_error(request, invite, "Некорректный тип партнёра")

    # Валидация имени
    if not name.strip():
        return _render_register_error(request, invite, "Укажите название или ФИО")

    # Определяем: залогинен ли пользователь
    existing_user = request.state.user

    if not existing_user:
        # Нужна регистрация нового пользователя
        if not email.strip():
            return _render_register_error(request, invite, "Укажите email")
        if len(password) < 8:
            return _render_register_error(request, invite, "Пароль должен быть не менее 8 символов")
        if password != password_confirm:
            return _render_register_error(request, invite, "Пароли не совпадают")

    try:
        user, partner = await register_partner_full(
            db,
            invite=valid_invite,
            email=email.strip() if not existing_user else None,
            password=password if not existing_user else None,
            existing_user=existing_user,
            name=name.strip(),
            partner_type=partner_type,
            inn=inn.strip() if inn.strip() else None,
            payout_details=payout_details.strip() if payout_details.strip() else None,
        )
    except ValueError as e:
        return _render_register_error(request, invite, str(e))

    # Создаём сессию если пользователь новый
    response = RedirectResponse(url="/partner/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    if not existing_user:
        await create_session(db, user.id, response)

    add_flash(response, "success", "Регистрация успешна! Придумайте промокод для привлечения пользователей.")
    return response


def _render_register_error(request: Request, invite: str, error: str):
    return templates.TemplateResponse(
        "partner/register.html",
        {
            "request": request,
            "invite_token": invite,
            "valid_invite": None,
            "invite_error": error,
        },
        status_code=422,
    )


@router.get("/dashboard")
async def partner_dashboard_page(
    request: Request,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Личный кабинет партнёра. НЕ требует is_onboarded."""
    partner = await get_partner_by_user_id(db, user.id)
    if not partner:
        raise HTTPException(status_code=403, detail="Доступ запрещён. Вы не являетесь партнёром.")
    if not partner.is_active:
        raise HTTPException(status_code=403, detail="Ваша партнёрская учётная запись деактивирована.")

    promo = await get_partner_promo(db, user.id)
    stats = await get_partner_stats(db, user.id)

    base_url = str(request.base_url).rstrip("/")
    partner_link = f"{base_url}/register?ref={promo.code}" if promo and promo.status == "approved" else None

    return templates.TemplateResponse(
        "partner/dashboard.html",
        {
            "request": request,
            "user": user,
            "partner": partner,
            "promo": promo,
            "stats": stats,
            "partner_link": partner_link,
            "partner_bonus_days": settings.PARTNER_BONUS_DAYS,
            "commission_percent": settings.PARTNER_COMMISSION_PERCENT,
        },
    )


@router.post("/propose-promo", dependencies=[Depends(require_csrf)])
async def partner_propose_promo(
    request: Request,
    code: str = Form(...),
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    partner = await get_partner_by_user_id(db, user.id)
    if not partner:
        raise HTTPException(status_code=403, detail="Доступ запрещён")

    existing = await get_partner_promo(db, user.id)
    if existing:
        response = RedirectResponse(url="/partner/dashboard", status_code=status.HTTP_303_SEE_OTHER)
        add_flash(response, "warning", "У вас уже есть промокод. Создать новый нельзя.")
        return response

    try:
        await propose_partner_promo_code(db, partner, code)
        response = RedirectResponse(url="/partner/dashboard", status_code=status.HTTP_303_SEE_OTHER)
        add_flash(response, "success", "Промокод отправлен на модерацию")
        return response
    except ValueError as e:
        response = RedirectResponse(url="/partner/dashboard", status_code=status.HTTP_303_SEE_OTHER)
        add_flash(response, "error", str(e))
        return response


@router.post("/update-profile", dependencies=[Depends(require_csrf)])
async def partner_update_profile(
    request: Request,
    name: str = Form(...),
    partner_type: str = Form(...),
    inn: str = Form(default=""),
    payout_details: str = Form(default=""),
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    partner = await get_partner_by_user_id(db, user.id)
    if not partner:
        raise HTTPException(status_code=403, detail="Доступ запрещён")

    if partner_type not in VALID_PARTNER_TYPES:
        response = RedirectResponse(url="/partner/dashboard", status_code=status.HTTP_303_SEE_OTHER)
        add_flash(response, "error", "Некорректный тип партнёра")
        return response

    await update_partner_profile(
        db, partner,
        name=name.strip(),
        partner_type=partner_type,
        inn=inn.strip() if inn.strip() else None,
        payout_details=payout_details.strip() if payout_details.strip() else None,
    )

    response = RedirectResponse(url="/partner/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    add_flash(response, "success", "Профиль обновлён")
    return response