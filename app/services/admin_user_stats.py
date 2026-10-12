"""Сервис статистики по пользователям для админки."""
import logging
from datetime import date, datetime, timedelta, timezone
from sqlalchemy import select, func, and_, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.lesson import Lesson
from app.models.user_word import UserWord
from app.models.subscription import Subscription
from app.models.partner import Partner
from app.utils.streak import calculate_streak

logger = logging.getLogger(__name__)

# Количество месяцев для когорт
COHORT_MONTHS = 6
# Количество дней для графика регистраций
REGISTRATION_CHART_DAYS = 30
# Размер топа
TOP_LIMIT = 10
# Для стриков берём юзеров, активных за последние N дней
STREAK_ACTIVITY_DAYS = 60


async def get_user_stats(db: AsyncSession) -> dict:
    """
    Возвращает полную статистику по пользователям.

    Returns:
        {
            "summary": {...},
            "registrations_chart": [...],
            "levels": {...},
            "dictionaries": {...},
            "activity": {...},
            "cohorts": [...],
            "top_lessons_week": [...],
            "top_streaks": [...],
            "top_words": [...],
        }
    """
    today = date.today()
    now = datetime.now(timezone.utc)

    # 1. Сводка
    summary = await _get_summary(db, today, now)

    # 2. График регистраций (последние 30 дней)
    registrations_chart = await _get_registrations_chart(db, today)

    # 3. Распределения
    levels = await _get_levels_distribution(db)
    dictionaries = await _get_dictionaries_distribution(db)

    # 4. Активность
    activity = await _get_activity(db, today)

    # 5. Когорты / Retention
    cohorts = await _get_cohorts(db, today)

    # 6. Топ-таблицы
    top_lessons_week = await _get_top_lessons_week(db, today)
    top_streaks = await _get_top_streaks(db, today)
    top_words = await _get_top_words(db)

    return {
        "summary": summary,
        "registrations_chart": registrations_chart,
        "levels": levels,
        "dictionaries": dictionaries,
        "activity": activity,
        "cohorts": cohorts,
        "top_lessons_week": top_lessons_week,
        "top_streaks": top_streaks,
        "top_words": top_words,
    }


async def _get_summary(db: AsyncSession, today: date, now: datetime) -> dict:
    """Сводные карточки."""
    today_start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    stmt = select(
        func.count(User.id).label("total"),
        func.count(User.id).filter(User.is_onboarded == True).label("onboarded"),  # noqa: E712
        func.count(User.id).filter(User.created_at >= today_start).label("new_today"),
        func.count(User.id).filter(User.created_at >= week_ago).label("new_7d"),
        func.count(User.id).filter(User.created_at >= month_ago).label("new_30d"),
    )
    row = (await db.execute(stmt)).one()

    # Премиум активные
    premium_stmt = select(func.count(func.distinct(Subscription.user_id))).where(
        Subscription.status == "active",
        Subscription.expires_at > now,
    )
    premium_count = (await db.execute(premium_stmt)).scalar() or 0

    # Партнёры активные
    partners_stmt = select(func.count(Partner.id)).where(Partner.is_active == True)  # noqa: E712
    partners_count = (await db.execute(partners_stmt)).scalar() or 0

    onboarded = row.onboarded or 0
    conversion_pct = round(premium_count / onboarded * 100, 1) if onboarded > 0 else 0.0

    return {
        "total": row.total or 0,
        "onboarded": onboarded,
        "new_today": row.new_today or 0,
        "new_7d": row.new_7d or 0,
        "new_30d": row.new_30d or 0,
        "premium": premium_count,
        "conversion_pct": conversion_pct,
        "partners": partners_count,
    }


async def _get_registrations_chart(db: AsyncSession, today: date) -> list[dict]:
    """Данные для графика регистраций по дням (последние 30 дней)."""
    start_date = today - timedelta(days=REGISTRATION_CHART_DAYS - 1)
    start_dt = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)

    stmt = (
        select(
            func.date(User.created_at).label("reg_date"),
            func.count(User.id).label("cnt"),
        )
        .where(User.created_at >= start_dt)
        .group_by(func.date(User.created_at))
    )
    rows = (await db.execute(stmt)).all()

    # Преобразуем в словарь {дата: количество}
    counts = {str(r.reg_date): r.cnt for r in rows}

    # Генерируем все даты и заполняем нулями
    chart = []
    for i in range(REGISTRATION_CHART_DAYS):
        d = start_date + timedelta(days=i)
        chart.append({
            "date": d.isoformat(),
            "label": d.strftime("%d.%m"),
            "count": counts.get(d.isoformat(), 0),
        })

    return chart


async def _get_levels_distribution(db: AsyncSession) -> dict:
    """Распределение по уровням (только онборженные)."""
    stmt = (
        select(User.level, func.count(User.id))
        .where(User.is_onboarded == True)  # noqa: E712
        .group_by(User.level)
    )
    rows = (await db.execute(stmt)).all()

    result = {}
    level_order = ["A1", "A2", "B1", "B2", "C1", "C2"]
    for lvl in level_order:
        result[lvl] = 0
    for lvl, cnt in rows:
        if lvl in result:
            result[lvl] = cnt
        else:
            result["—"] = result.get("—", 0) + cnt

    return result


async def _get_dictionaries_distribution(db: AsyncSession) -> dict:
    """Распределение по словарям (только онборженные)."""
    stmt = (
        select(User.dictionary_code, func.count(User.id))
        .where(User.is_onboarded == True)  # noqa: E712
        .group_by(User.dictionary_code)
    )
    rows = (await db.execute(stmt)).all()

    labels = {"general": "Общий", "it": "IT", "travel": "Путешествия"}
    result = {}
    for code, cnt in rows:
        label = labels.get(code, code or "—")
        result[label] = cnt

    return result


async def _get_activity(db: AsyncSession, today: date) -> dict:
    """DAU / WAU / MAU / churn."""
    week_ago_date = today - timedelta(days=7)
    month_ago_date = today - timedelta(days=30)
    churn_cutoff = today - timedelta(days=14)

    # DAU / WAU / MAU
    activity_stmt = select(
        func.count(func.distinct(Lesson.user_id)).filter(
            Lesson.started_local_date == today
        ).label("dau"),
        func.count(func.distinct(Lesson.user_id)).filter(
            Lesson.started_local_date >= week_ago_date
        ).label("wau"),
        func.count(func.distinct(Lesson.user_id)).filter(
            Lesson.started_local_date >= month_ago_date
        ).label("mau"),
    )
    activity_row = (await db.execute(activity_stmt)).one()

    # Churn risk: онборженные, но не было урока 14+ дней
    churn_stmt = select(func.count(User.id)).where(
        User.is_onboarded == True,  # noqa: E712
        ~User.id.in_(
            select(Lesson.user_id).where(
                Lesson.started_local_date >= churn_cutoff
            )
        ),
    )
    churn_14d = (await db.execute(churn_stmt)).scalar() or 0

    return {
        "dau": activity_row.dau or 0,
        "wau": activity_row.wau or 0,
        "mau": activity_row.mau or 0,
        "churn_14d": churn_14d,
    }


async def _get_cohorts(db: AsyncSession, today: date) -> list[dict]:
    """
    Когортный анализ (последние 6 месяцев).
    Для каждой когорты (месяц регистрации):
    - размер когорты
    - % активных на неделе 1 (1-7 день после регистрации)
    - % активных на неделе 2 (8-14 день)
    - % активных на неделе 3 (15-21 день)
    - % активных на неделе 4+ (22+ день)
    """
    # Определяем границы когорт
    cohort_months = []
    for i in range(COHORT_MONTHS - 1, -1, -1):
        # Вычисляем месяц, отступая на i месяцев назад
        year = today.year
        month = today.month - i
        while month <= 0:
            month += 12
            year -= 1
        cohort_months.append((year, month))

    # Загружаем юзеров за последние 6 месяцев
    earliest_cohort = cohort_months[0]
    earliest_dt = datetime(
        earliest_cohort[0], earliest_cohort[1], 1, tzinfo=timezone.utc
    )

    users_stmt = select(User.id, User.created_at).where(
        User.is_onboarded == True,  # noqa: E712
        User.created_at >= earliest_dt,
    )
    users_rows = (await db.execute(users_stmt)).all()

    if not users_rows:
        return []

    user_ids = [u.id for u in users_rows]
    user_created = {u.id: u.created_at for u in users_rows}

    # Загружаем уроки для этих юзеров
    lessons_stmt = select(
        Lesson.user_id,
        Lesson.started_at,
    ).where(
        Lesson.user_id.in_(user_ids),
        Lesson.started_at >= earliest_dt,
    )
    lessons_rows = (await db.execute(lessons_stmt)).all()

    # Группируем уроки по юзерам
    user_lessons: dict[int, list[datetime]] = {}
    for user_id, started_at in lessons_rows:
        if user_id not in user_lessons:
            user_lessons[user_id] = []
        user_lessons[user_id].append(started_at)

    # Строим когорты
    cohorts = []
    for year, month in cohort_months:
        cohort_label = f"{month:02d}.{year}"

        # Юзеры этой когорты
        cohort_user_ids = []
        for uid, created_at in user_created.items():
            if created_at.year == year and created_at.month == month:
                cohort_user_ids.append(uid)

        cohort_size = len(cohort_user_ids)
        if cohort_size == 0:
            cohorts.append({
                "label": cohort_label,
                "size": 0,
                "weeks": [None, None, None, None],
            })
            continue

        # Для каждой недели считаем, сколько юзеров были активны
        week_counts = [0, 0, 0, 0]  # недели 1-4
        for uid in cohort_user_ids:
            created = user_created[uid]
            lessons = user_lessons.get(uid, [])
            weeks_hit = set()
            for lesson_at in lessons:
                delta_days = (lesson_at - created).days
                if delta_days < 0:
                    continue
                if delta_days < 7:
                    weeks_hit.add(0)
                elif delta_days < 14:
                    weeks_hit.add(1)
                elif delta_days < 21:
                    weeks_hit.add(2)
                else:
                    weeks_hit.add(3)
            for w in weeks_hit:
                week_counts[w] += 1

        # Проверяем, какие недели прошли для этой когорты
        # Последняя дата когорты: конец месяца
        if month == 12:
            cohort_end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            cohort_end = datetime(year, month + 1, 1, tzinfo=timezone.utc)

        days_since_cohort_end = (datetime.now(timezone.utc) - cohort_end).days

        weeks = []
        for w in range(4):
            # Неделя w доступна, если прошло >= (w+1)*7 дней с конца когорты
            required_days = (w + 1) * 7
            if days_since_cohort_end >= required_days:
                pct = round(week_counts[w] / cohort_size * 100, 1)
                weeks.append(pct)
            else:
                weeks.append(None)  # данные ещё не полные

        cohorts.append({
            "label": cohort_label,
            "size": cohort_size,
            "weeks": weeks,
        })

    return cohorts


async def _get_top_lessons_week(db: AsyncSession, today: date) -> list[dict]:
    """Топ-10 по урокам за последние 7 дней."""
    week_ago_date = today - timedelta(days=7)

    stmt = (
        select(
            User.email,
            func.count(Lesson.id).label("cnt"),
        )
        .join(Lesson, Lesson.user_id == User.id)
        .where(Lesson.started_local_date >= week_ago_date)
        .group_by(User.id, User.email)
        .order_by(func.count(Lesson.id).desc())
        .limit(TOP_LIMIT)
    )
    rows = (await db.execute(stmt)).all()

    return [
        {"email": _mask_email(r.email), "value": r.cnt}
        for r in rows
    ]


async def _get_top_streaks(db: AsyncSession, today: date) -> list[dict]:
    """Топ-10 по текущему стрику."""
    cutoff_date = today - timedelta(days=STREAK_ACTIVITY_DAYS)

    # Берём юзеров, активных за последние 60 дней
    active_stmt = (
        select(Lesson.user_id)
        .where(Lesson.started_local_date >= cutoff_date)
        .group_by(Lesson.user_id)
        .order_by(func.count(Lesson.id).desc())
        .limit(100)
    )
    active_user_ids = (await db.execute(active_stmt)).scalars().all()

    if not active_user_ids:
        return []

    # Загружаем даты завершённых уроков для этих юзеров
    dates_stmt = (
        select(
            Lesson.user_id,
            Lesson.started_local_date,
        )
        .where(
            Lesson.user_id.in_(active_user_ids),
            Lesson.completed_local_date.isnot(None),
        )
    )
    dates_rows = (await db.execute(dates_stmt)).all()

    # Группируем по юзерам
    user_dates: dict[int, list[date]] = {}
    for user_id, d in dates_rows:
        if user_id not in user_dates:
            user_dates[user_id] = []
        user_dates[user_id].append(d)

    # Считаем стрики
    streaks = []
    for uid, dates in user_dates.items():
        result = calculate_streak(dates, today)
        if result["current"] > 0:
            streaks.append({"user_id": uid, "streak": result["current"]})

    # Сортируем и берём топ
    streaks.sort(key=lambda x: x["streak"], reverse=True)
    top_streaks = streaks[:TOP_LIMIT]

    # Загружаем email для топ юзеров
    if not top_streaks:
        return []

    top_ids = [s["user_id"] for s in top_streaks]
    emails_stmt = select(User.id, User.email).where(User.id.in_(top_ids))
    emails_rows = (await db.execute(emails_stmt)).all()
    email_map = {r.id: r.email for r in emails_rows}

    return [
        {"email": _mask_email(email_map.get(s["user_id"], "—")), "value": s["streak"]}
        for s in top_streaks
    ]


async def _get_top_words(db: AsyncSession) -> list[dict]:
    """Топ-10 по количеству активных слов."""
    stmt = (
        select(
            User.email,
            func.count(UserWord.id).label("cnt"),
        )
        .join(UserWord, UserWord.user_id == User.id)
        .where(UserWord.status == "active")
        .group_by(User.id, User.email)
        .order_by(func.count(UserWord.id).desc())
        .limit(TOP_LIMIT)
    )
    rows = (await db.execute(stmt)).all()

    return [
        {"email": _mask_email(r.email), "value": r.cnt}
        for r in rows
    ]


def _mask_email(email: str) -> str:
    """Маскирует email для отображения."""
    if not email or "@" not in email:
        return email or "—"
    local, domain = email.split("@", 1)
    if len(local) <= 1:
        masked_local = local + "***"
    else:
        masked_local = local[0] + "***"
    return f"{masked_local}@{domain}"