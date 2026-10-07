from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.user import User
from app.models.lesson import Lesson
from app.models.user_word import UserWord
from app.utils.datetime_utils import get_user_today
from app.utils.streak import calculate_streak

async def get_dashboard_data(db: AsyncSession, user: User) -> dict:
    today = get_user_today(user.timezone)
    
    # 1. Уроков сегодня
    stmt_lessons_today = select(func.count(Lesson.id)).where(
        Lesson.user_id == user.id,
        Lesson.started_local_date == today
    )
    result = await db.execute(stmt_lessons_today)
    lessons_today = result.scalar_one_or_none() or 0
    
    # 2. Незавершенный урок
    stmt_in_progress = select(Lesson).where(
        Lesson.user_id == user.id,
        Lesson.status == 'in_progress'
    )
    result_ip = await db.execute(stmt_in_progress)
    in_progress_lesson = result_ip.scalar_one_or_none()
    
    # 3. Сводка по словам
    stmt_words = select(
        UserWord.status,
        func.count(UserWord.id)
    ).where(
        UserWord.user_id == user.id
    ).group_by(UserWord.status)
    
    result_words = await db.execute(stmt_words)
    word_summary = {"active": 0, "mastered": 0, "ignored": 0}
    for row in result_words:
        if row[0] in word_summary:
            word_summary[row[0]] = row[1]
        
    # 4. Стрик (берем только завершенные уроки)
    stmt_dates = select(Lesson.started_local_date).where(
        Lesson.user_id == user.id,
        Lesson.completed_local_date.isnot(None)
    )
    result_dates = await db.execute(stmt_dates)
    completed_dates = [row[0] for row in result_dates]
    streak = calculate_streak(completed_dates, today)
    
    # 5. Определение CTA (Call To Action)
    if in_progress_lesson:
        cta = "resume"
        cta_lesson_id = in_progress_lesson.id
    elif lessons_today >= user.daily_lesson_limit:
        cta = "limit_reached"
        cta_lesson_id = None
    else:
        cta = "start"
        cta_lesson_id = None
        
    return {
        "lessons_today": lessons_today,
        "daily_lesson_limit": user.daily_lesson_limit,
        "in_progress_lesson": in_progress_lesson,
        "word_summary": word_summary,
        "streak": streak,
        "cta": cta,
        "cta_lesson_id": cta_lesson_id,
        "today": today
    }