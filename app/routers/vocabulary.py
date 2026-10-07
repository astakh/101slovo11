"""Роуты словаря пользователя."""
from fastapi import APIRouter, Request, Depends, Form, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.deps import require_auth, require_csrf
from app.core.templates import templates
from app.models.user import User
from app.services.vocabulary import get_vocabulary, get_word_card, change_word_status
from app.utils.flash import add_flash

router = APIRouter(prefix="/vocabulary", tags=["vocabulary"])


@router.get("")
async def vocabulary_list(
    request: Request,
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Список слов пользователя с пагинацией и фильтрами."""
    if not user.is_onboarded:
        return RedirectResponse(url="/onboarding", status_code=status.HTTP_303_SEE_OTHER)

    data = await get_vocabulary(
        db,
        user,
        status=status_filter,
        q=q,
        page=page,
    )
    return templates.TemplateResponse(
        "vocabulary/list.html",
        {"request": request, "user": user, **data},
    )


@router.get("/{word_id}")
async def vocabulary_word(
    request: Request,
    word_id: int,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Карточка слова."""
    if not user.is_onboarded:
        return RedirectResponse(url="/onboarding", status_code=status.HTTP_303_SEE_OTHER)

    try:
        data = await get_word_card(db, user, word_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Слово не найдено")

    return templates.TemplateResponse(
        "vocabulary/word.html",
        {"request": request, "user": user, **data},
    )


@router.post("/{word_id}/status", dependencies=[Depends(require_csrf)])
async def vocabulary_status(
    request: Request,
    word_id: int,
    action: str = Form(...),
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Смена статуса слова (HTMX или обычный запрос)."""
    try:
        await change_word_status(db, user, word_id, action)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Перезагружаем данные для рендера
    data = await get_word_card(db, user, word_id)

    # Для HTMX возвращаем частичный шаблон кнопок
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            "vocabulary/_word_actions.html",
            {
                "request": request,
                "word": data["word"],
                "user_word": data["user_word"],
            },
        )

    # Для обычных запросов — редирект обратно с flash
    response = RedirectResponse(
        url=f"/vocabulary/{word_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    add_flash(response, "success", "Статус слова обновлён")
    return response