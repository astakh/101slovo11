# app/routers/vocabulary.py
"""Роуты словаря пользователя."""
import logging
from fastapi import APIRouter, Request, Depends, Form, HTTPException, Query, status
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.deps import require_auth, require_csrf
from app.core.templates import templates
from app.models.user import User
from app.models.word import Word
from app.services.vocabulary import get_vocabulary, get_word_card, change_word_status
from app.services.vocabulary_add import (
    search_and_enrich,
    add_word_to_user,
    validate_lemma_input,
)
from app.llm.gigachat import GigaChatError
from app.utils.flash import add_flash

logger = logging.getLogger(__name__)

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


# ============================================================
# ВАЖНО: эти роуты ДОЛЖНЫ быть ДО /{word_id},
# иначе FastAPI воспримет "search" как word_id
# ============================================================

@router.post("/search", dependencies=[Depends(require_csrf)])
async def vocabulary_search(
    lemma: str = Form(...),
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Поиск слова в базе. Если не найдено — генерация через LLM
    и добавление в words. Возвращает JSON.
    """
    lemma = lemma.strip()

    # Валидация входного слова
    error = validate_lemma_input(lemma)
    if error:
        return JSONResponse({"error": error}, status_code=400)

    try:
        result = await search_and_enrich(db, user, lemma)
    except GigaChatError as e:
        logger.error(f"[SEARCH] GigaChatError: {e.code} - {e}")
        return JSONResponse(
            {"error": f"Ошибка генерации: {e}"},
            status_code=503,
        )

    return JSONResponse(result)


@router.post("/add-selected", dependencies=[Depends(require_csrf)])
async def vocabulary_add_selected(
    word_ids: list[int] = Form(...),
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Добавление выбранных слов в словарь пользователя."""
    if not word_ids:
        return JSONResponse({"error": "Не выбрано ни одного слова"}, status_code=400)

    added = 0
    for word_id in word_ids:
        stmt = select(Word).where(Word.id == word_id)
        result = await db.execute(stmt)
        word = result.scalar_one_or_none()
        if word:
            await add_word_to_user(db, user, word)
            added += 1

    await db.commit()
    return JSONResponse({"added": added})


# ============================================================
# Роуты с /{word_id} — ПОСЛЕ фиксированных путей
# ============================================================

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
    """Смена статуса слова."""
    try:
        await change_word_status(db, user, word_id, action)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    data = await get_word_card(db, user, word_id)

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            "vocabulary/_word_actions.html",
            {
                "request": request,
                "word": data["word"],
                "user_word": data["user_word"],
            },
        )

    response = RedirectResponse(
        url=f"/vocabulary/{word_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    add_flash(response, "success", "Статус слова обновлён")
    return response