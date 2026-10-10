"""Роуты для юридических страниц."""
from fastapi import APIRouter, Request

from app.core.templates import templates
from app.config import settings

router = APIRouter(prefix="/legal", tags=["legal"])


@router.get("/offer")
async def legal_offer(request: Request):
    """Публичная оферта на подписку."""
    return templates.TemplateResponse(
        "legal/offer.html",
        {
            "request": request,
            "referral_bonus_days": settings.REFERRAL_BONUS_DAYS,
            # ✅ Лимиты из конфига (вместо хардкода)
            "free_daily_limit": settings.FREE_LESSON_PER_DAY_LIMIT,
            "free_lessons_total": settings.FREE_LESSONS_TOTAL_LIMIT,
            "daily_lesson_limit_max": settings.DAILY_LESSON_LIMIT_MAX,
            "words_per_lesson_max": settings.WORDS_PER_LESSON_MAX,
        },
    )


@router.get("/privacy")
async def legal_privacy(request: Request):
    """Политика конфиденциальности."""
    return templates.TemplateResponse(
        "legal/privacy.html",
        {"request": request},
    )


@router.get("/consent")
async def legal_consent(request: Request):
    """Согласие на обработку персональных данных."""
    return templates.TemplateResponse(
        "legal/consent.html",
        {"request": request},
    )


@router.get("/terms")
async def legal_terms(request: Request):
    """Условия использования сервиса."""
    return templates.TemplateResponse(
        "legal/terms.html",
        {"request": request},
    )