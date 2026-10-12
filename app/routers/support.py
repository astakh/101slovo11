# app/routers/support.py
"""Роуты обращений в поддержку для пользователей."""
import logging
from fastapi import APIRouter, Request, Depends, Form, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.deps import require_auth, require_csrf
from app.core.templates import templates
from app.models.user import User
from app.services.support import (
    create_ticket,
    add_user_reply,
    get_user_tickets,
    get_ticket_with_messages,
    mark_ticket_viewed_by_user,
    validate_ticket_input,
    VALID_CATEGORIES,
    CATEGORY_LABELS,
    MAX_MESSAGE_LENGTH,
    MAX_SUBJECT_LENGTH,
)
from app.utils.flash import add_flash

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/support", tags=["support"])


@router.get("")
async def support_list(
    request: Request,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Список своих тикетов."""
    if not user.is_onboarded:
        return RedirectResponse(url="/onboarding", status_code=status.HTTP_303_SEE_OTHER)

    tickets = await get_user_tickets(db, user)
    return templates.TemplateResponse(
        "support/list.html",
        {
            "request": request,
            "user": user,
            "tickets": tickets,
        },
    )


@router.get("/new")
async def support_new_form(
    request: Request,
    user: User = Depends(require_auth),
):
    """Форма создания нового тикета."""
    if not user.is_onboarded:
        return RedirectResponse(url="/onboarding", status_code=status.HTTP_303_SEE_OTHER)

    categories = [
        {"code": code, "label": CATEGORY_LABELS[code]}
        for code in VALID_CATEGORIES
    ]
    return templates.TemplateResponse(
        "support/new.html",
        {
            "request": request,
            "user": user,
            "categories": categories,
            "max_subject_length": MAX_SUBJECT_LENGTH,
            "max_message_length": MAX_MESSAGE_LENGTH,
            "form": {"category": "", "subject": "", "content": ""},
            "errors": [],
        },
    )


@router.post("/new", dependencies=[Depends(require_csrf)])
async def support_create(
    request: Request,
    category: str = Form(...),
    subject: str = Form(...),
    content: str = Form(...),
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Создание нового тикета."""
    if not user.is_onboarded:
        return RedirectResponse(url="/onboarding", status_code=status.HTTP_303_SEE_OTHER)

    errors = validate_ticket_input(category, subject, content)
    if errors:
        categories = [
            {"code": code, "label": CATEGORY_LABELS[code]}
            for code in VALID_CATEGORIES
        ]
        return templates.TemplateResponse(
            "support/new.html",
            {
                "request": request,
                "user": user,
                "categories": categories,
                "max_subject_length": MAX_SUBJECT_LENGTH,
                "max_message_length": MAX_MESSAGE_LENGTH,
                "form": {
                    "category": category,
                    "subject": subject,
                    "content": content,
                },
                "errors": errors,
            },
            status_code=422,
        )

    try:
        ticket = await create_ticket(
            db, user,
            category=category,
            subject=subject,
            content=content,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    response = RedirectResponse(
        url=f"/support/{ticket.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    add_flash(response, "success", "Обращение создано. Мы ответим в ближайшее время.")
    return response


@router.get("/{ticket_id}")
async def support_ticket_view(
    request: Request,
    ticket_id: int,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Просмотр тикета (переписка)."""
    if not user.is_onboarded:
        return RedirectResponse(url="/onboarding", status_code=status.HTTP_303_SEE_OTHER)

    data = await get_ticket_with_messages(db, ticket_id)
    if not data or data["ticket"].user_id != user.id:
        raise HTTPException(status_code=404, detail="Обращение не найдено")

    await mark_ticket_viewed_by_user(db, user, ticket_id)

    return templates.TemplateResponse(
        "support/ticket.html",
        {
            "request": request,
            "user": user,
            **data,
            "max_message_length": MAX_MESSAGE_LENGTH,
            "is_admin_view": False,
        },
    )


@router.post("/{ticket_id}/reply", dependencies=[Depends(require_csrf)])
async def support_user_reply(
    request: Request,
    ticket_id: int,
    content: str = Form(...),
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Пользователь отвечает в тикете."""
    if not user.is_onboarded:
        return RedirectResponse(url="/onboarding", status_code=status.HTTP_303_SEE_OTHER)

    is_htmx = bool(request.headers.get("HX-Request"))

    try:
        await add_user_reply(db, user, ticket_id, content)
    except ValueError as e:
        if is_htmx:
            return templates.TemplateResponse(
                "support/_reply_error.html",
                {"request": request, "error": str(e)},
                status_code=422,
            )
        response = RedirectResponse(
            url=f"/support/{ticket_id}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
        add_flash(response, "error", str(e))
        return response

    if is_htmx:
        data = await get_ticket_with_messages(db, ticket_id)
        return templates.TemplateResponse(
            "support/_messages.html",
            {
                "request": request,
                "user": user,
                **data,
                "is_admin_view": False,
            },
            headers={"HX-Trigger": "supportReplySent"},
        )

    return RedirectResponse(
        url=f"/support/{ticket_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )