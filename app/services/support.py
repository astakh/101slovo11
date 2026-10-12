# app/services/support.py
"""Сервис работы с обращениями в поддержку."""
import logging
from datetime import datetime, timezone
from sqlalchemy import select, func, case, or_
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import User
from app.models.support_ticket import SupportTicket
from app.models.support_message import SupportMessage
from app.models.partner import Partner

logger = logging.getLogger(__name__)

VALID_CATEGORIES = {"question", "suggestion", "problem", "other"}
VALID_STATUSES = {"open", "in_progress", "resolved", "closed"}

CATEGORY_LABELS = {
    "question": "Вопрос",
    "suggestion": "Предложение",
    "problem": "Проблема",
    "other": "Другое",
}

STATUS_LABELS = {
    "open": "Открыт",
    "in_progress": "В работе",
    "resolved": "Решён",
    "closed": "Закрыт",
}

MAX_MESSAGE_LENGTH = 5000
MAX_SUBJECT_LENGTH = 200


# ============================================================
# ВАЛИДАЦИЯ
# ============================================================
def validate_ticket_input(category: str, subject: str, content: str) -> list[str]:
    """Валидирует данные для создания тикета."""
    errors: list[str] = []
    if category not in VALID_CATEGORIES:
        errors.append("Некорректная категория")
    subject = (subject or "").strip()
    if not subject:
        errors.append("Укажите тему обращения")
    elif len(subject) > MAX_SUBJECT_LENGTH:
        errors.append(f"Тема слишком длинная (максимум {MAX_SUBJECT_LENGTH} символов)")
    content = (content or "").strip()
    if not content:
        errors.append("Напишите сообщение")
    elif len(content) > MAX_MESSAGE_LENGTH:
        errors.append(f"Сообщение слишком длинное (максимум {MAX_MESSAGE_LENGTH} символов)")
    return errors


def validate_message_content(content: str) -> str | None:
    """Валидирует текст сообщения. Возвращает ошибку или None."""
    content = (content or "").strip()
    if not content:
        return "Сообщение не может быть пустым"
    if len(content) > MAX_MESSAGE_LENGTH:
        return f"Сообщение слишком длинное (максимум {MAX_MESSAGE_LENGTH} символов)"
    return None


# ============================================================
# СОЗДАНИЕ ТИКЕТА
# ============================================================
async def create_ticket(
    db: AsyncSession,
    user: User,
    *,
    category: str,
    subject: str,
    content: str,
) -> SupportTicket:
    """Создаёт новый тикет с первым сообщением."""
    errors = validate_ticket_input(category, subject, content)
    if errors:
        raise ValueError(" ".join(errors))

    now = datetime.now(timezone.utc)
    ticket = SupportTicket(
        user_id=user.id,
        category=category.strip(),
        subject=subject.strip(),
        status="open",
        last_user_message_at=now,
        user_last_viewed_at=now,
    )
    db.add(ticket)
    await db.flush()

    message = SupportMessage(
        ticket_id=ticket.id,
        author_id=user.id,
        content=content.strip(),
    )
    db.add(message)
    await db.flush()

    logger.info(
        f"[SUPPORT] Ticket #{ticket.id} created by user {user.id}, "
        f"category={category}"
    )
    return ticket


# ============================================================
# ОТВЕТ В ТИКЕТЕ
# ============================================================
async def add_user_reply(
    db: AsyncSession,
    user: User,
    ticket_id: int,
    content: str,
) -> SupportTicket:
    """Пользователь пишет сообщение в свой тикет."""
    error = validate_message_content(content)
    if error:
        raise ValueError(error)

    ticket = await _get_user_ticket(db, user.id, ticket_id)
    if not ticket:
        raise ValueError("Тикет не найден")

    now = datetime.now(timezone.utc)
    message = SupportMessage(
        ticket_id=ticket.id,
        author_id=user.id,
        content=content.strip(),
    )
    db.add(message)

    ticket.last_user_message_at = now
    ticket.user_last_viewed_at = now
    # Если тикет был resolved/closed — возвращаем в open
    if ticket.status in ("resolved", "closed"):
        ticket.status = "open"
        ticket.closed_at = None

    await db.flush()
    await db.refresh(ticket)
    return ticket


async def add_admin_reply(
    db: AsyncSession,
    admin: User,
    ticket_id: int,
    content: str,
) -> SupportTicket:
    """Админ пишет сообщение в тикет."""
    error = validate_message_content(content)
    if error:
        raise ValueError(error)

    ticket = await _get_ticket_by_id(db, ticket_id)
    if not ticket:
        raise ValueError("Тикет не найден")

    now = datetime.now(timezone.utc)
    message = SupportMessage(
        ticket_id=ticket.id,
        author_id=admin.id,
        content=content.strip(),
    )
    db.add(message)

    ticket.last_admin_message_at = now
    ticket.admin_last_viewed_at = now
    # Авто-перевод в in_progress если был open
    if ticket.status == "open":
        ticket.status = "in_progress"

    await db.flush()
    await db.refresh(ticket)
    return ticket


# ============================================================
# ПРОСМОТР ТИКЕТА (отметка "прочитано")
# ============================================================
async def mark_ticket_viewed_by_user(
    db: AsyncSession,
    user: User,
    ticket_id: int,
) -> SupportTicket | None:
    """Пользователь открыл тикет — обновляем user_last_viewed_at."""
    ticket = await _get_user_ticket(db, user.id, ticket_id)
    if not ticket:
        return None
    ticket.user_last_viewed_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(ticket)
    return ticket


async def mark_ticket_viewed_by_admin(
    db: AsyncSession,
    ticket_id: int,
) -> SupportTicket | None:
    """Админ открыл тикет — обновляем admin_last_viewed_at."""
    ticket = await _get_ticket_by_id(db, ticket_id)
    if not ticket:
        return None
    ticket.admin_last_viewed_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(ticket)
    return ticket


# ============================================================
# СМЕНА СТАТУСА (только админ)
# ============================================================
async def change_ticket_status(
    db: AsyncSession,
    admin: User,
    ticket_id: int,
    new_status: str,
) -> SupportTicket:
    """Админ меняет статус тикета."""
    if new_status not in VALID_STATUSES:
        raise ValueError("Некорректный статус")

    ticket = await _get_ticket_by_id(db, ticket_id)
    if not ticket:
        raise ValueError("Тикет не найден")

    ticket.status = new_status
    if new_status == "closed":
        ticket.closed_at = datetime.now(timezone.utc)
    else:
        ticket.closed_at = None

    await db.flush()
    await db.refresh(ticket)
    logger.info(
        f"[SUPPORT] Ticket #{ticket.id} status changed to {new_status} "
        f"by admin {admin.id}"
    )
    return ticket


# ============================================================
# УДАЛЕНИЕ СООБЩЕНИЯ (только админ, soft delete)
# ============================================================
async def delete_message(
    db: AsyncSession,
    admin: User,
    message_id: int,
) -> SupportMessage:
    """Админ удаляет сообщение (soft delete)."""
    stmt = select(SupportMessage).where(SupportMessage.id == message_id)
    result = await db.execute(stmt)
    message = result.scalar_one_or_none()
    if not message:
        raise ValueError("Сообщение не найдено")
    if message.is_deleted:
        raise ValueError("Сообщение уже удалено")

    message.is_deleted = True
    message.deleted_at = datetime.now(timezone.utc)
    message.deleted_by_admin_id = admin.id
    await db.flush()
    await db.refresh(message)
    logger.info(
        f"[SUPPORT] Message #{message.id} deleted by admin {admin.id}"
    )
    return message


# ============================================================
# СПИСКИ ТИКЕТОВ
# ============================================================
async def get_user_tickets(
    db: AsyncSession,
    user: User,
) -> list[dict]:
    """Возвращает список тикетов пользователя с метаданными."""
    stmt = (
        select(SupportTicket)
        .where(SupportTicket.user_id == user.id)
        .order_by(SupportTicket.created_at.desc())
    )
    result = await db.execute(stmt)
    tickets = result.scalars().all()

    items = []
    for t in tickets:
        msg_count_stmt = select(func.count(SupportMessage.id)).where(
            SupportMessage.ticket_id == t.id,
            SupportMessage.is_deleted == False,  # noqa: E712
        )
        msg_count = (await db.execute(msg_count_stmt)).scalar_one() or 0

        unread = False
        if t.last_admin_message_at and (
            t.user_last_viewed_at is None
            or t.last_admin_message_at > t.user_last_viewed_at
        ):
            unread = True

        items.append({
            "ticket": t,
            "messages_count": msg_count,
            "unread": unread,
            "category_label": CATEGORY_LABELS.get(t.category, t.category),
            "status_label": STATUS_LABELS.get(t.status, t.status),
        })
    return items


async def get_admin_tickets(
    db: AsyncSession,
    *,
    status_filter: str | None = None,
    category_filter: str | None = None,
) -> list[dict]:
    """Возвращает список всех тикетов для админа."""
    stmt = select(SupportTicket, User.email, User.id.label("author_id"))
    stmt = stmt.join(User, SupportTicket.user_id == User.id)

    if status_filter and status_filter in VALID_STATUSES:
        stmt = stmt.where(SupportTicket.status == status_filter)
    if category_filter and category_filter in VALID_CATEGORIES:
        stmt = stmt.where(SupportTicket.category == category_filter)

    sort_expr = case(
        (SupportTicket.status == "open", 0),
        (SupportTicket.status == "in_progress", 1),
        (SupportTicket.status == "resolved", 2),
        (SupportTicket.status == "closed", 3),
        else_=4,
    )
    stmt = stmt.order_by(
        sort_expr,
        func.coalesce(SupportTicket.last_user_message_at, SupportTicket.created_at).desc(),
    )

    result = await db.execute(stmt)
    rows = result.all()

    # Получаем ID всех пользователей для проверки партнёрства
    user_ids = [r.author_id for r in rows]
    partner_user_ids: set[int] = set()
    if user_ids:
        partner_stmt = select(Partner.user_id).where(
            Partner.user_id.in_(user_ids),
            Partner.is_active == True,  # noqa: E712
        )
        partner_result = await db.execute(partner_stmt)
        partner_user_ids = set(partner_result.scalars().all())

    items = []
    for ticket, email, author_id in rows:
        unread = False
        if ticket.last_user_message_at and (
            ticket.admin_last_viewed_at is None
            or ticket.last_user_message_at > ticket.admin_last_viewed_at
        ):
            unread = True

        items.append({
            "ticket": ticket,
            "user_email": email,
            "is_partner": author_id in partner_user_ids,
            "unread": unread,
            "category_label": CATEGORY_LABELS.get(ticket.category, ticket.category),
            "status_label": STATUS_LABELS.get(ticket.status, ticket.status),
        })
    return items


# ============================================================
# ПРОСМОТР ОДНОГО ТИКЕТА С СООБЩЕНИЯМИ
# ============================================================
async def get_ticket_with_messages(
    db: AsyncSession,
    ticket_id: int,
) -> dict | None:
    """Возвращает тикет со всеми сообщениями и авторами."""
    ticket = await _get_ticket_by_id(db, ticket_id)
    if not ticket:
        return None

    user_stmt = select(User).where(User.id == ticket.user_id)
    user_result = await db.execute(user_stmt)
    ticket_user = user_result.scalar_one_or_none()

    is_partner = False
    if ticket_user:
        partner_stmt = select(Partner.id).where(
            Partner.user_id == ticket_user.id,
            Partner.is_active == True,  # noqa: E712
        )
        partner_result = await db.execute(partner_stmt)
        is_partner = partner_result.scalar_one_or_none() is not None

    msg_stmt = (
        select(SupportMessage, User.email, User.is_admin)
        .join(User, SupportMessage.author_id == User.id)
        .where(SupportMessage.ticket_id == ticket_id)
        .order_by(SupportMessage.created_at.asc())
    )
    msg_result = await db.execute(msg_stmt)
    messages = []
    for message, author_email, author_is_admin in msg_result.all():
        messages.append({
            "message": message,
            "author_email": author_email,
            "is_admin": author_is_admin,
        })

    return {
        "ticket": ticket,
        "ticket_user": ticket_user,
        "is_partner": is_partner,
        "messages": messages,
        "category_label": CATEGORY_LABELS.get(ticket.category, ticket.category),
        "status_label": STATUS_LABELS.get(ticket.status, ticket.status),
    }


# ============================================================
# СЧЁТЧИКИ НЕПРОЧИТАННЫХ
# ============================================================
async def get_user_unread_count(db: AsyncSession, user_id: int) -> int:
    """Количество тикетов пользователя с непрочитанными ответами админа."""
    stmt = select(func.count(SupportTicket.id)).where(
        SupportTicket.user_id == user_id,
        SupportTicket.last_admin_message_at.isnot(None),
        or_(
            SupportTicket.user_last_viewed_at.is_(None),
            SupportTicket.last_admin_message_at > SupportTicket.user_last_viewed_at,
        ),
    )
    result = await db.execute(stmt)
    return result.scalar_one() or 0


async def get_admin_unread_count(db: AsyncSession) -> int:
    """Количество тикетов с непрочитанными сообщениями от пользователей."""
    stmt = select(func.count(SupportTicket.id)).where(
        SupportTicket.status.in_(("open", "in_progress")),
        SupportTicket.last_user_message_at.isnot(None),
        or_(
            SupportTicket.admin_last_viewed_at.is_(None),
            SupportTicket.last_user_message_at > SupportTicket.admin_last_viewed_at,
        ),
    )
    result = await db.execute(stmt)
    return result.scalar_one() or 0


# ============================================================
# ВНУТРЕННИЕ ХЕЛПЕРЫ
# ============================================================
async def _get_user_ticket(
    db: AsyncSession,
    user_id: int,
    ticket_id: int,
) -> SupportTicket | None:
    """Получает тикет, принадлежащий пользователю."""
    stmt = select(SupportTicket).where(
        SupportTicket.id == ticket_id,
        SupportTicket.user_id == user_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _get_ticket_by_id(
    db: AsyncSession,
    ticket_id: int,
) -> SupportTicket | None:
    """Получает тикет по ID (для админа)."""
    stmt = select(SupportTicket).where(SupportTicket.id == ticket_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()