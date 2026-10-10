"""Роуты для настроек пользователя."""
from fastapi import APIRouter, Request, Depends, Form, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_auth, require_csrf
from app.services.settings import update_user_settings
from app.core.templates import templates
from app.models.user import User
from app.config import settings
from app.utils.flash import add_flash

router = APIRouter(tags=["settings"])

LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]
DICT_LABELS = {
    "general": "Общий",
    "it": "IT",
    "travel": "Путешествия",
}


def get_dictionaries() -> list[dict]:
    return [
        {
            "code": code,
            "name": DICT_LABELS.get(code, code),
        }
        for code in settings.AVAILABLE_DICTIONARIES
    ]


def render_settings(
    request: Request,
    user: User,
    error: str | None = None,
    form: dict | None = None,
):
    form = form or {}
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "levels": LEVELS,
            "dictionaries": get_dictionaries(),
            "user": user,
            "error": error,
            "form": form,
            "settings": settings,
            # ✅ Передаём параметры для settings_form.html
            "form_action": "/settings",
            "submit_text": "Сохранить настройки",
            "submit_icon": "save",
        },
    )

@router.get("/settings")
async def settings_page(
    request: Request,
    user: User = Depends(require_auth),
):
    """Страница настроек."""
    if not user.is_onboarded:
        return RedirectResponse(url="/onboarding", status_code=status.HTTP_303_SEE_OTHER)

    return render_settings(request, user)


@router.post("/settings", dependencies=[Depends(require_csrf)])
async def settings_post(
    request: Request,
    level: str = Form(...),
    dictionary_code: str = Form(...),
    words_per_lesson: int = Form(...),
    daily_lesson_limit: int = Form(...),
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Обновление настроек."""
    if not user.is_onboarded:
        return RedirectResponse(url="/onboarding", status_code=status.HTTP_303_SEE_OTHER)

    form = {
        "level": level,
        "dictionary_code": dictionary_code,
        "words_per_lesson": words_per_lesson,
        "daily_lesson_limit": daily_lesson_limit,
    }

    # Валидация уровня
    if level not in LEVELS:
        return render_settings(
            request,
            user,
            error="Некорректный уровень английского языка.",
            form=form,
        )

    # Валидация словаря
    if dictionary_code not in settings.AVAILABLE_DICTIONARIES:
        return render_settings(
            request,
            user,
            error="Некорректный словарь.",
            form=form,
        )

    # Валидация слов в уроке
    if not (
        settings.WORDS_PER_LESSON_MIN
        <= words_per_lesson
        <= settings.WORDS_PER_LESSON_MAX
    ):
        return render_settings(
            request,
            user,
            error=(
                f"Количество слов в уроке должно быть "
                f"от {settings.WORDS_PER_LESSON_MIN} "
                f"до {settings.WORDS_PER_LESSON_MAX}."
            ),
            form=form,
        )

    # Валидация лимита уроков
    if not (1 <= daily_lesson_limit <= settings.DAILY_LESSON_LIMIT_MAX):
        return render_settings(
            request,
            user,
            error=(
                f"Лимит уроков в день должен быть "
                f"от 1 до {settings.DAILY_LESSON_LIMIT_MAX}."
            ),
            form=form,
        )

    # Обновление настроек
    try:
        await update_user_settings(
            db=db,
            user=user,
            level=level,
            dictionary_code=dictionary_code,
            words_per_lesson=words_per_lesson,
            daily_lesson_limit=daily_lesson_limit,
        )
    except ValueError as e:
        return render_settings(
            request,
            user,
            error=str(e),
            form=form,
        )

    response = RedirectResponse(url="/settings", status_code=status.HTTP_303_SEE_OTHER)
    add_flash(response, "success", "Настройки успешно сохранены!")
    return response