from fastapi import APIRouter, Request, Depends, Form, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.deps import require_auth, require_csrf
from app.services.onboarding import complete_onboarding
from app.core.templates import templates
from app.models.user import User
from app.config import settings

router = APIRouter(tags=["onboarding"])

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


def render_onboarding(
    request: Request,
    user: User,
    error: str | None = None,
    form: dict | None = None,
):
    form = form or {}
    return templates.TemplateResponse(
        "onboarding.html",
        {
            "request": request,
            "levels": LEVELS,
            "dictionaries": get_dictionaries(),
            "user": user,
            "error": error,
            "form": form,
            "settings": settings,
            # ✅ Передаём параметры для settings_form.html
            "form_action": "/onboarding/complete",
            "submit_text": "Начать обучение",
            "submit_icon": "rocket",
        },
    )


@router.get("/onboarding")
async def onboarding_page(
    request: Request,
    user: User = Depends(require_auth),
):
    if user.is_onboarded:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return render_onboarding(request, user)


@router.post(
    "/onboarding/complete",
    dependencies=[Depends(require_csrf)],
)
async def onboarding_complete(
    request: Request,
    level: str = Form(...),
    dictionary_code: str = Form(...),
    words_per_lesson: int = Form(...),
    daily_lesson_limit: int = Form(...),
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    if user.is_onboarded:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    form = {
        "level": level,
        "dictionary_code": dictionary_code,
        "words_per_lesson": words_per_lesson,
        "daily_lesson_limit": daily_lesson_limit,
    }

    if level not in LEVELS:
        return render_onboarding(
            request,
            user,
            error="Некорректный уровень английского языка.",
            form=form,
        )

    if dictionary_code not in settings.AVAILABLE_DICTIONARIES:
        return render_onboarding(
            request,
            user,
            error="Некорректный словарь.",
            form=form,
        )

    if not (
        settings.WORDS_PER_LESSON_MIN
        <= words_per_lesson
        <= settings.WORDS_PER_LESSON_MAX
    ):
        return render_onboarding(
            request,
            user,
            error=(
                f"Количество слов в уроке должно быть "
                f"от {settings.WORDS_PER_LESSON_MIN} "
                f"до {settings.WORDS_PER_LESSON_MAX}."
            ),
            form=form,
        )

    if not (1 <= daily_lesson_limit <= settings.DAILY_LESSON_LIMIT_MAX):
        return render_onboarding(
            request,
            user,
            error=(
                f"Лимит уроков в день должен быть "
                f"от 1 до {settings.DAILY_LESSON_LIMIT_MAX}."
            ),
            form=form,
        )

    try:
        await complete_onboarding(
            db=db,
            user=user,
            level=level,
            dictionary_code=dictionary_code,
            words_per_lesson=words_per_lesson,
            daily_lesson_limit=daily_lesson_limit,
        )
    except ValueError as e:
        return render_onboarding(
            request,
            user,
            error=str(e),
            form=form,
        )

    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)