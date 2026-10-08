"""Админские роуты."""

from fastapi import APIRouter, Request, Depends, Form, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.deps import require_admin, require_csrf
from app.core.templates import templates
from app.models.user import User
from app.services.admin_prompts import (
    get_all_prompts,
    update_prompt,
    validate_prompt_template,
)
from app.services.admin_stats import get_token_stats
from app.utils.flash import add_flash

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/prompts")
async def admin_prompts_page(
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Список промптов с возможностью редактирования."""
    prompts = await get_all_prompts(db)
    return templates.TemplateResponse(
        "admin/prompts.html",
        {
            "request": request,
            "user": admin,
            "prompts": prompts,
            "error": None,
            "edit_key": None,
            "edit_value": None,
        },
    )


@router.post("/prompts/{key}", dependencies=[Depends(require_csrf)])
async def admin_prompt_update(
    request: Request,
    key: str,
    system_template: str = Form(...),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Обновление промпта."""
    # Валидация
    errors = validate_prompt_template(key, system_template)
    if errors:
        prompts = await get_all_prompts(db)
        return templates.TemplateResponse(
            "admin/prompts.html",
            {
                "request": request,
                "user": admin,
                "prompts": prompts,
                "error": " ".join(errors),
                "edit_key": key,
                "edit_value": system_template,
            },
            status_code=422,
        )

    # Обновление
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
    """Статистика расхода токенов."""
    stats = await get_token_stats(db)
    return templates.TemplateResponse(
        "admin/stats.html",
        {
            "request": request,
            "user": admin,
            "stats": stats,
        },
    )