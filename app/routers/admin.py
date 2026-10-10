"""Админские роуты."""
from fastapi import APIRouter, Request, Depends, Form, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.deps import require_admin, require_csrf
from app.core.templates import templates
from app.models.user import User
from app.services.admin_prompts import get_all_prompts, update_prompt, validate_prompt_template
from app.services.admin_stats import get_token_stats
from app.services.partner import (
    create_partner_invite,
    get_all_invites,
    get_pending_promo_codes,
    approve_promo_code,
    decline_promo_code,
    get_all_partners,
    deactivate_partner,
    get_partner_earnings,
    mark_earning_as_paid,
)
from app.config import settings
from app.utils.flash import add_flash

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/prompts")
async def admin_prompts_page(
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    prompts = await get_all_prompts(db)
    return templates.TemplateResponse(
        "admin/prompts.html",
        {"request": request, "user": admin, "prompts": prompts, "error": None, "edit_key": None, "edit_value": None},
    )


@router.post("/prompts/{key}", dependencies=[Depends(require_csrf)])
async def admin_prompt_update(
    request: Request,
    key: str,
    system_template: str = Form(...),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    errors = validate_prompt_template(key, system_template)
    if errors:
        prompts = await get_all_prompts(db)
        return templates.TemplateResponse(
            "admin/prompts.html",
            {"request": request, "user": admin, "prompts": prompts, "error": " ".join(errors), "edit_key": key, "edit_value": system_template},
            status_code=422,
        )
    try:
        await update_prompt(db, key, system_template, admin)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    response = RedirectResponse(url="/admin/prompts", status_code=status.HTTP_303_SEE_OTHER)
    add_flash(response, "success", f"Промпт '{key}' обновлён")
    return response


@router.get("/stats")
async def admin_stats_page(
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    stats = await get_token_stats(db)
    return templates.TemplateResponse("admin/stats.html", {"request": request, "user": admin, "stats": stats})


# ============================================================
# PARTNERS MANAGEMENT
# ============================================================

@router.get("/partners")
async def admin_partners_page(
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    partners_data = await get_all_partners(db)
    invites = await get_all_invites(db)
    pending_promos = await get_pending_promo_codes(db)

    base_url = str(request.base_url).rstrip("/")
    invites_with_links = []
    for inv in invites:
        link = f"{base_url}/partner/register?invite={inv.token}" if not inv.is_used else None
        invites_with_links.append({"invite": inv, "link": link})

    return templates.TemplateResponse(
        "admin/partners.html",
        {
            "request": request,
            "user": admin,
            "partners_data": partners_data,
            "invites_with_links": invites_with_links,
            "pending_promos": pending_promos,
            "min_payout_rub": settings.PARTNER_MIN_PAYOUT_KOP / 100,
        },
    )


@router.post("/partners/create-invite", dependencies=[Depends(require_csrf)])
async def admin_create_invite(
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    invite = await create_partner_invite(db, admin)
    response = RedirectResponse(url="/admin/partners", status_code=status.HTTP_303_SEE_OTHER)
    add_flash(response, "success", f"Инвайт создан: {invite.token[:16]}...")
    return response


@router.post("/partners/approve-promo/{promo_id}", dependencies=[Depends(require_csrf)])
async def admin_approve_promo(
    request: Request,
    promo_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        await approve_promo_code(db, promo_id, admin)
        response = RedirectResponse(url="/admin/partners", status_code=status.HTTP_303_SEE_OTHER)
        add_flash(response, "success", "Промокод подтверждён")
        return response
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/partners/decline-promo/{promo_id}", dependencies=[Depends(require_csrf)])
async def admin_decline_promo(
    request: Request,
    promo_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        await decline_promo_code(db, promo_id, admin)
        response = RedirectResponse(url="/admin/partners", status_code=status.HTTP_303_SEE_OTHER)
        add_flash(response, "info", "Промокод отклонён")
        return response
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/partners/deactivate/{partner_id}", dependencies=[Depends(require_csrf)])
async def admin_deactivate_partner(
    request: Request,
    partner_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        await deactivate_partner(db, partner_id, admin)
        response = RedirectResponse(url="/admin/partners", status_code=status.HTTP_303_SEE_OTHER)
        add_flash(response, "success", "Партнёр деактивирован")
        return response
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/partners/{partner_user_id}/earnings")
async def admin_partner_earnings_page(
    request: Request,
    partner_user_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    earnings = await get_partner_earnings(db, partner_user_id)
    return templates.TemplateResponse(
        "admin/partner_earnings.html",
        {"request": request, "user": admin, "partner_user_id": partner_user_id, "earnings": earnings},
    )


@router.post("/partners/mark-paid/{earning_id}", dependencies=[Depends(require_csrf)])
async def admin_mark_paid(
    request: Request,
    earning_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        await mark_earning_as_paid(db, earning_id, admin)
        response = RedirectResponse(url="/admin/partners", status_code=status.HTTP_303_SEE_OTHER)
        add_flash(response, "success", "Отмечено как выплаченное")
        return response
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))