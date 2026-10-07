"""Сервис для работы со словарём пользователя."""
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import User
from app.models.word import Word
from app.models.user_word import UserWord
from app.models.event import Event

ITEMS_PER_PAGE = 20

VALID_STATUSES = {"active", "mastered", "ignored"}


async def get_vocabulary(
    db: AsyncSession,
    user: User,
    *,
    status: str | None = None,
    q: str | None = None,
    page: int = 1,
    per_page: int = ITEMS_PER_PAGE,
) -> dict:
    """
    Возвращает страницу словаря пользователя с фильтрами.
    """
    base_query = (
        select(UserWord, Word)
        .join(Word, UserWord.word_id == Word.id)
        .where(UserWord.user_id == user.id)
    )

    if status and status in VALID_STATUSES:
        base_query = base_query.where(UserWord.status == status)

    if q:
        like = f"%{q.strip()}%"
        base_query = base_query.where(
            or_(
                Word.lemma.ilike(like),
                func.array_to_string(Word.translations, ",").ilike(like),
            )
        )

    # Подсчёт общего количества
    count_stmt = select(func.count()).select_from(base_query.subquery())
    total = (await db.execute(count_stmt)).scalar_one() or 0

    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))

    # Данные страницы
    stmt = (
        base_query.order_by(Word.lemma.asc(), Word.id.asc())
        .limit(per_page)
        .offset((page - 1) * per_page)
    )
    rows = (await db.execute(stmt)).all()

    items = []
    for uw, word in rows:
        due_in_lessons = 0
        if uw.status == "active" and uw.due_lesson_number is not None:
            due_in_lessons = max(uw.due_lesson_number - user.last_lesson_number, 0)
        items.append({
            "word_id": word.id,
            "lemma": word.lemma,
            "pos": word.pos,
            "level": word.level,
            "translations": word.translations,
            "status": uw.status,
            "stage": uw.stage,
            "due_in_lessons": due_in_lessons,
        })

    return {
        "items": items,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "status": status,
        "q": q or "",
    }


async def get_word_card(
    db: AsyncSession,
    user: User,
    word_id: int,
) -> dict:
    """
    Карточка слова: глобальное слово + запись пользователя (если есть).
    """
    stmt = select(Word).where(Word.id == word_id)
    word = (await db.execute(stmt)).scalar_one_or_none()
    if not word:
        raise ValueError("Слово не найдено")

    stmt_uw = select(UserWord).where(
        UserWord.user_id == user.id,
        UserWord.word_id == word_id,
    )
    user_word = (await db.execute(stmt_uw)).scalar_one_or_none()

    due_in_lessons = 0
    if user_word and user_word.status == "active" and user_word.due_lesson_number is not None:
        due_in_lessons = max(user_word.due_lesson_number - user.last_lesson_number, 0)

    return {
        "word": word,
        "user_word": user_word,
        "due_in_lessons": due_in_lessons,
    }


async def change_word_status(
    db: AsyncSession,
    user: User,
    word_id: int,
    action: str,
) -> UserWord:
    """
    Меняет статус слова пользователя.

    Переходы (согласно ТЗ):
    - active → ignored          (action="ignore")
    - ignored → active          (action="activate", stage=0, due=last+1)
    - mastered → active         (action="activate", stage=0, due=last+1)

    Если записи нет в user_words:
    - action="activate" создаёт запись со статусом "active".
    - action="ignore" — ошибка.

    Args:
        db: сессия БД.
        user: пользователь.
        word_id: ID глобального слова.
        action: "activate" или "ignore".

    Returns:
        Обновлённый/созданный UserWord.

    Raises:
        ValueError: при некорректном действии или переходе.
    """
    stmt = select(UserWord).where(
        UserWord.user_id == user.id,
        UserWord.word_id == word_id,
    )
    user_word = (await db.execute(stmt)).scalar_one_or_none()

    if action == "activate":
        if not user_word:
            # Создаём новую запись (добавление слова в словарь)
            user_word = UserWord(
                user_id=user.id,
                word_id=word_id,
                status="active",
                stage=0,
                due_lesson_number=user.last_lesson_number + 1,
                source="dictionary",
            )
            db.add(user_word)
        else:
            if user_word.status == "active":
                # Ничего не меняем
                return user_word
            # ignored → active, mastered → active
            user_word.status = "active"
            user_word.stage = 0
            user_word.due_lesson_number = user.last_lesson_number + 1
    elif action == "ignore":
        if not user_word:
            raise ValueError("Слово ещё не добавлено в словарь")
        if user_word.status != "active":
            raise ValueError("Игнорировать можно только активное слово")
        user_word.status = "ignored"
    else:
        raise ValueError("Неизвестное действие")

    # Событие
    event = Event(
        user_id=user.id,
        type="word_status_changed",
        payload={"word_id": word_id, "action": action},
    )
    db.add(event)

    await db.flush()
    await db.refresh(user_word)
    return user_word