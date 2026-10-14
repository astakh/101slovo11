# app/routers/admin.py
"""Админские роуты."""
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Depends, Form, HTTPException, status, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.deps import require_admin, require_csrf
from app.core.templates import templates
from app.models.user import User
from app.models.event import Event
from app.services.admin_prompts import get_all_prompts, update_prompt, validate_prompt_template
from app.services.admin_stats import get_token_stats
from app.services.admin_user_stats import get_user_stats
from app.services.subscription import (
    activate_subscription,
    get_subscription_status,
)
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
from app.services.support import (
    get_admin_tickets,
    get_ticket_with_messages,
    add_admin_reply,
    change_ticket_status,
    delete_message,
    mark_ticket_viewed_by_admin,
    VALID_CATEGORIES,
    VALID_STATUSES,
    CATEGORY_LABELS,
    STATUS_LABELS,
    MAX_MESSAGE_LENGTH,
)
from app.services.word_page import (
    get_word_pages_list,
    get_queue_items,
    add_words_to_queue,
    delete_queue_item,
    search_words_for_admin,
    process_queue_batch,
    regenerate_word_page,
    publish_word_page,
    archive_word_page,
)
from app.services.vocabulary_add import search_and_enrich, validate_lemma_input
from app.llm.gigachat import GigaChatError
from app.config import settings
from app.utils.flash import add_flash

logger = logging.getLogger(__name__)

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
# USERS MANAGEMENT
# ============================================================

@router.get("/users")
async def admin_users_page(
    request: Request,
    email: str = "",
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Страница поиска пользователя по email и начисления дней."""
    found_user = None
    sub_status = None
    search_error = None

    if email.strip():
        stmt = select(User).where(User.email == email.strip().lower())
        result = await db.execute(stmt)
        found_user = result.scalar_one_or_none()
        if found_user:
            sub_status = await get_subscription_status(db, found_user.id)
        else:
            search_error = f"Пользователь с email '{email.strip()}' не найден"

    return templates.TemplateResponse(
        "admin/users.html",
        {
            "request": request,
            "user": admin,
            "found_user": found_user,
            "sub_status": sub_status,
            "search_email": email.strip(),
            "search_error": search_error,
            "active_tab": "search",
        },
    )

@router.get("/users/stats")
async def admin_user_stats_page(
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Страница статистики по пользователям."""
    stats = await get_user_stats(db)
    return templates.TemplateResponse(
        "admin/user_stats.html",
        {
            "request": request,
            "user": admin,
            "stats": stats,
            "active_tab": "stats",
        },
    )

@router.post("/users/grant-days", dependencies=[Depends(require_csrf)])
async def admin_grant_days(
    request: Request,
    user_id: int = Form(...),
    days: int = Form(...),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Начисление дней Premium пользователю (без оплаты)."""
    if days < 1:
        raise HTTPException(status_code=400, detail="Количество дней должно быть не менее 1")

    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    target_user = result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    await activate_subscription(
        db,
        user_id=target_user.id,
        plan="admin_bonus",
        source="admin",
        extra_days=days,
    )

    event = Event(
        user_id=target_user.id,
        type="admin_days_granted",
        payload={
            "days": days,
            "admin_user_id": admin.id,
            "admin_email": admin.email,
            "granted_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    db.add(event)
    await db.flush()

    response = RedirectResponse(
        url=f"/admin/users?email={target_user.email}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    add_flash(response, "success", f"Пользователю {target_user.email} начислено {days} дн. Premium")
    return response

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

# ============================================================
# SUPPORT (обращения в поддержку)
# ============================================================

@router.get("/support")
async def admin_support_list(
    request: Request,
    status_filter: str | None = Query(default=None, alias="status"),
    category_filter: str | None = Query(default=None, alias="category"),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Список всех обращений в поддержку."""
    tickets = await get_admin_tickets(
        db,
        status_filter=status_filter,
        category_filter=category_filter,
    )
    return templates.TemplateResponse(
        "admin/support_list.html",
        {
            "request": request,
            "user": admin,
            "tickets": tickets,
            "status_filter": status_filter,
            "category_filter": category_filter,
            "valid_statuses": VALID_STATUSES,
            "valid_categories": VALID_CATEGORIES,
            "status_labels": STATUS_LABELS,
            "category_labels": CATEGORY_LABELS,
        },
    )

@router.get("/support/{ticket_id}")
async def admin_support_ticket_view(
    request: Request,
    ticket_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Просмотр тикета поддержки админом."""
    data = await get_ticket_with_messages(db, ticket_id)
    if not data:
        raise HTTPException(status_code=404, detail="Обращение не найдено")
    await mark_ticket_viewed_by_admin(db, ticket_id)
    return templates.TemplateResponse(
        "admin/support_ticket.html",
        {
            "request": request,
            "user": admin,
            **data,
            "max_message_length": MAX_MESSAGE_LENGTH,
            "valid_statuses": VALID_STATUSES,
            "status_labels": STATUS_LABELS,
            "is_admin_view": True,
        },
    )

@router.post("/support/{ticket_id}/reply", dependencies=[Depends(require_csrf)])
async def admin_support_reply(
    request: Request,
    ticket_id: int,
    content: str = Form(...),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Админ отвечает в тикете."""
    is_htmx = bool(request.headers.get("HX-Request"))
    try:
        await add_admin_reply(db, admin, ticket_id, content)
    except ValueError as e:
        if is_htmx:
            return templates.TemplateResponse(
                "support/_reply_error.html",
                {"request": request, "error": str(e)},
                status_code=422,
            )
        response = RedirectResponse(
            url=f"/admin/support/{ticket_id}",
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
                "user": admin,
                **data,
                "is_admin_view": True,
            },
            headers={"HX-Trigger": "supportReplySent"},
        )

    return RedirectResponse(
        url=f"/admin/support/{ticket_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )

@router.post("/support/{ticket_id}/status", dependencies=[Depends(require_csrf)])
async def admin_support_change_status(
    request: Request,
    ticket_id: int,
    new_status: str = Form(...),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Админ меняет статус тикета."""
    try:
        await change_ticket_status(db, admin, ticket_id, new_status)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    response = RedirectResponse(
        url=f"/admin/support/{ticket_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    add_flash(response, "success", f"Статус изменён на «{STATUS_LABELS.get(new_status, new_status)}»")
    return response

@router.post("/support/messages/{message_id}/delete", dependencies=[Depends(require_csrf)])
async def admin_support_delete_message(
    request: Request,
    message_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Админ удаляет сообщение (soft delete)."""
    try:
        message = await delete_message(db, admin, message_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    ticket_id = message.ticket_id
    is_htmx = bool(request.headers.get("HX-Request"))

    if is_htmx:
        return templates.TemplateResponse(
            "support/_deleted_message.html",
            {"request": request, "message_id": message_id},
        )

    response = RedirectResponse(
        url=f"/admin/support/{ticket_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    add_flash(response, "success", "Сообщение удалено")
    return response

# ============================================================
# WORD PAGES (SEO-страницы слов)
# ============================================================

@router.get("/word-pages")
async def admin_word_pages_list(
    request: Request,
    status_filter: str | None = Query(default=None, alias="status"),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Список всех страниц слов."""
    valid_statuses = {"draft", "published", "archived"}
    if status_filter and status_filter not in valid_statuses:
        status_filter = None
    items = await get_word_pages_list(db, status_filter=status_filter)
    return templates.TemplateResponse(
        "admin/word_pages.html",
        {
            "request": request,
            "user": admin,
            "items": items,
            "status_filter": status_filter,
            "valid_statuses": valid_statuses,
        },
    )

@router.get("/word-pages/queue")
async def admin_word_pages_queue(
    request: Request,
    q: str = "",
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Очередь генерации страниц слов + поиск слов для добавления."""
    queue_items = await get_queue_items(db)

    # Поиск слов для автокомплита
    search_results = []
    if q.strip():
        search_results = await search_words_for_admin(db, q)

    # Проверяем, есть ли точное совпадение леммы
    exact_match = any(
        w.lemma.lower() == q.strip().lower()
        for w in search_results
    ) if q.strip() else False

    return templates.TemplateResponse(
        "admin/word_page_queue.html",
        {
            "request": request,
            "user": admin,
            "queue_items": queue_items,
            "search_results": search_results,
            "search_query": q.strip(),
            "exact_match": exact_match,
        },
    )

@router.post("/word-pages/queue/add", dependencies=[Depends(require_csrf)])
async def admin_word_pages_queue_add(
    request: Request,
    word_ids: list[int] = Form(...),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Добавление слов в очередь генерации."""
    if not word_ids:
        response = RedirectResponse(
            url="/admin/word-pages/queue",
            status_code=status.HTTP_303_SEE_OTHER,
        )
        add_flash(response, "warning", "Не выбрано ни одного слова")
        return response

    added, warnings = await add_words_to_queue(db, word_ids)

    response = RedirectResponse(
        url="/admin/word-pages/queue",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    if added > 0:
        add_flash(response, "success", f"Добавлено в очередь: {added} слов")
    for warning in warnings:
        add_flash(response, "info", warning)
    return response

@router.post("/word-pages/queue/generate-word", dependencies=[Depends(require_csrf)])
async def admin_word_pages_generate_word(
    request: Request,
    lemma: str = Form(...),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Генерация слова через LLM и добавление в таблицу words.
    Использует существующую функцию search_and_enrich.
    После генерации редирект на поиск — слово будет найдено.
    """
    lemma = lemma.strip()

    # Валидация входного слова
    error = validate_lemma_input(lemma)
    if error:
        response = RedirectResponse(
            url="/admin/word-pages/queue",
            status_code=status.HTTP_303_SEE_OTHER,
        )
        add_flash(response, "error", error)
        return response

    try:
        result = await search_and_enrich(db, admin, lemma)
    except GigaChatError as e:
        logger.error(f"[ADMIN] GigaChatError generating word '{lemma}': {e.code} - {e}")
        response = RedirectResponse(
            url=f"/admin/word-pages/queue?q={lemma}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
        add_flash(response, "error", f"Ошибка LLM при генерации '{lemma}': {str(e)[:200]}")
        return response
    except Exception as e:
        logger.error(f"[ADMIN] Error generating word '{lemma}': {e}")
        response = RedirectResponse(
            url=f"/admin/word-pages/queue?q={lemma}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
        add_flash(response, "error", f"Ошибка генерации '{lemma}': {str(e)[:200]}")
        return response

    words = result.get("words", [])
    source = result.get("source", "db")

    response = RedirectResponse(
        url=f"/admin/word-pages/queue?q={lemma}",
        status_code=status.HTTP_303_SEE_OTHER,
    )

    if not words:
        add_flash(response, "warning", f"Не удалось сгенерировать данные для '{lemma}'. Проверьте написание.")
    elif source == "db":
        add_flash(response, "info", f"Слово '{lemma}' уже есть в базе ({len(words)} вариант(ов))")
    else:
        added_lemmas = ", ".join(f"{w['lemma']} ({w['pos']})" for w in words)
        add_flash(response, "success", f"Сгенерировано и добавлено в базу: {added_lemmas}")

    return response

@router.post("/word-pages/queue/{queue_id}/delete", dependencies=[Depends(require_csrf)])
async def admin_word_pages_queue_delete(
    request: Request,
    queue_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Удаление элемента из очереди."""
    success = await delete_queue_item(db, queue_id)
    response = RedirectResponse(
        url="/admin/word-pages/queue",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    if success:
        add_flash(response, "success", "Элемент удалён из очереди")
    else:
        add_flash(response, "error", "Не удалось удалить элемент (статус не позволяет)")
    return response

@router.post("/word-pages/generate-batch", dependencies=[Depends(require_csrf)])
async def admin_word_pages_generate_batch(
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Запуск батч-генерации очереди."""
    result = await process_queue_batch(db, admin.id)
    response = RedirectResponse(
        url="/admin/word-pages/queue",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    if result["total"] == 0:
        add_flash(response, "info", "Очередь пуста — нечего генерировать")
    else:
        msg = f"Сгенерировано: {result['generated']}, ошибок: {result['errors']}"
        if result["errors"] > 0:
            add_flash(response, "warning", msg)
        else:
            add_flash(response, "success", msg)
    return response

@router.post("/word-pages/{word_page_id}/publish", dependencies=[Depends(require_csrf)])
async def admin_word_page_publish(
    request: Request,
    word_page_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Публикация страницы слова."""
    try:
        page = await publish_word_page(db, word_page_id, admin.id)
        response = RedirectResponse(
            url="/admin/word-pages",
            status_code=status.HTTP_303_SEE_OTHER,
        )
        add_flash(response, "success", f"Страница '{page.slug}' опубликована")
        return response
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/word-pages/{word_page_id}/archive", dependencies=[Depends(require_csrf)])
async def admin_word_page_archive(
    request: Request,
    word_page_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Архивация страницы слова."""
    try:
        page = await archive_word_page(db, word_page_id, admin.id)
        response = RedirectResponse(
            url="/admin/word-pages",
            status_code=status.HTTP_303_SEE_OTHER,
        )
        add_flash(response, "success", f"Страница '{page.slug}' архивирована")
        return response
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/word-pages/{word_page_id}/regenerate", dependencies=[Depends(require_csrf)])
async def admin_word_page_regenerate(
    request: Request,
    word_page_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Перегенерация контента страницы слова."""
    try:
        page = await regenerate_word_page(db, word_page_id, admin.id)
        response = RedirectResponse(
            url="/admin/word-pages",
            status_code=status.HTTP_303_SEE_OTHER,
        )
        add_flash(response, "success", f"Страница '{page.slug}' перегенерирована")
        return response
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[ADMIN] Error regenerating word_page {word_page_id}: {e}")
        response = RedirectResponse(
            url="/admin/word-pages",
            status_code=status.HTTP_303_SEE_OTHER,
        )
        add_flash(response, "error", f"Ошибка перегенерации: {str(e)[:200]}")
        return response