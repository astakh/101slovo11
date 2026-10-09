"""Роуты для уроков."""
import logging

from fastapi import APIRouter, Request, Depends, Form, status, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.db import get_db
from app.deps import require_auth, require_csrf
from app.core.templates import templates
from app.models.user import User
from app.models.lesson import Lesson
from app.models.lesson_exercise import LessonExercise
from app.models.user_word import UserWord
from app.models.word import Word
from app.models.event import Event
from app.services.lesson_preview import build_lesson_preview
from app.services.lesson_start import start_lesson, LessonStartError
from app.services.lesson_evaluate import evaluate_exercise, LessonEvaluateError
from app.services.lesson_summary import get_lesson_summary
from app.services.lesson_resume import get_resume_info
from app.services.paywall import check_lesson_access, get_effective_daily_limit
from app.services.subscription import is_premium
from app.config import settings
from app.llm.gigachat import GigaChatError
from app.utils.text_validation import compute_lemma_key
from app.utils.datetime_utils import get_user_today
from app.utils.flash import add_flash

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/lesson", tags=["lesson"])


def _non_htmx_evaluate_success_redirect(result: dict) -> RedirectResponse:
    """
    Фолбэк-редирект для нативного POST-запроса, если по какой-то причине
    не сработал HTMX.
    """
    lesson_id = result["lesson_id"]
    if result.get("lesson_completed"):
        url = f"/lesson/{lesson_id}/summary"
    else:
        url = f"/lesson/{lesson_id}"

    response = RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)

    evaluation = result.get("evaluation") or {}
    eval_status = evaluation.get("status", "")
    feedback = evaluation.get("feedback", "")

    if eval_status == "correct":
        add_flash(response, "success", feedback or "Перевод проверен")
    elif eval_status == "typo":
        add_flash(response, "info", feedback or "Почти верно, есть небольшие недочёты")
    else:
        add_flash(response, "warning", feedback or "Перевод неверный")

    return response


def _non_htmx_evaluate_error_redirect(
    lesson_id: int | None,
    message: str,
    *,
    to_summary: bool = False,
    category: str = "error",
) -> RedirectResponse:
    """
    Фолбэк-редирект для ошибок при нативном POST-запросе.
    """
    if lesson_id is None:
        url = "/dashboard"
    elif to_summary:
        url = f"/lesson/{lesson_id}/summary"
    else:
        url = f"/lesson/{lesson_id}"

    response = RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)
    add_flash(response, category, message)
    return response


@router.get("/preview")
async def lesson_preview_page(
    request: Request,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Страница подбора слов для урока."""
    if not user.is_onboarded:
        return RedirectResponse(url="/onboarding", status_code=status.HTTP_303_SEE_OTHER)

    # Проверка незавершённого урока
    stmt_ip = select(Lesson).where(
        Lesson.user_id == user.id,
        Lesson.status == "in_progress",
    )
    result_ip = await db.execute(stmt_ip)
    in_progress = result_ip.scalar_one_or_none()

    if in_progress:
        return RedirectResponse(
            url=f"/lesson/{in_progress.id}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    # === ПРОВЕРКА ПЕЙВОЛЛА (общий лимит для freemium) ===
    access = await check_lesson_access(db, user)

    if not access["allowed"]:
        return templates.TemplateResponse(
            "lesson/preview.html",
            {
                "request": request,
                "user": user,
                "limit_reached": True,
                "paywall_reason": access["reason"],
                "is_premium": False,
                "lessons_today": 0,
                "daily_lesson_limit": 0,
                "free_lessons_remaining": access.get("free_lessons_remaining"),
            },
        )

    # === ПРОВЕРКА ДНЕВНОГО ЛИМИТА ===
    premium = access["is_premium"]
    effective_daily_limit = get_effective_daily_limit(user, premium)
    today = get_user_today(user.timezone)

    stmt_today = select(func.count(Lesson.id)).where(
        Lesson.user_id == user.id,
        Lesson.started_local_date == today,
    )
    result_today = await db.execute(stmt_today)
    lessons_today = result_today.scalar_one_or_none() or 0

    if lessons_today >= effective_daily_limit:
        return templates.TemplateResponse(
            "lesson/preview.html",
            {
                "request": request,
                "user": user,
                "limit_reached": True,
                "paywall_reason": "daily_limit",
                "is_premium": premium,
                "lessons_today": lessons_today,
                "daily_lesson_limit": effective_daily_limit,
                "free_lessons_remaining": access.get("free_lessons_remaining"),
            },
        )

    # Строим превью
    preview = await build_lesson_preview(db, user)

    return templates.TemplateResponse(
        "lesson/preview.html",
        {
            "request": request,
            "user": user,
            "limit_reached": False,
            "paywall_reason": None,
            "is_premium": premium,
            "free_lessons_remaining": access.get("free_lessons_remaining"),
            **preview,
        },
    )


@router.post("/start", dependencies=[Depends(require_csrf)])
async def lesson_start_post(
    request: Request,
    idempotency_key: str = Form(...),
    word_ids: list[int] = Form(...),
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Старт урока (идемпотентный)."""
    if not user.is_onboarded:
        return RedirectResponse(url="/onboarding", status_code=status.HTTP_303_SEE_OTHER)

    # === ПРОВЕРКА ПЕЙВОЛЛА (общий лимит для freemium) ===
    access = await check_lesson_access(db, user)
    if not access["allowed"]:
        if request.headers.get("HX-Request"):
            return templates.TemplateResponse(
                "lesson/preview.html",
                {
                    "request": request,
                    "user": user,
                    "error": "Бесплатные уроки исчерпаны. Подключите Premium для продолжения.",
                },
                status_code=422,
            )
        raise HTTPException(status_code=422, detail="Бесплатные уроки исчерпаны")

    logger.info(
        f"🚀 Начало старта урока | user_id={user.id} | "
        f"idempotency_key={idempotency_key[:16]}... | word_ids={word_ids}"
    )

    try:
        lesson = await start_lesson(
            db,
            user,
            idempotency_key=idempotency_key,
            word_ids=word_ids,
        )
    except LessonStartError as e:
        logger.warning(f"⚠️ LessonStartError: {e.code} - {e}")
        if request.headers.get("HX-Request"):
            return templates.TemplateResponse(
                "lesson/preview.html",
                {"request": request, "user": user, "error": str(e)},
                status_code=422,
            )
        raise HTTPException(status_code=422, detail=str(e))
    except GigaChatError as e:
        logger.error(
            f"🚨 GigaChatError during lesson start | Code: {e.code} | "
            f"Message: {e} | HTTP Status: {e.http_status}"
        )
        if request.headers.get("HX-Request"):
            return templates.TemplateResponse(
                "errors/503.html",
                {"request": request, "error": str(e)},
                status_code=503,
            )
        raise HTTPException(status_code=503, detail="LLM недоступен. Попробуйте позже.")

    logger.info(
        f"✅ Урок успешно создан | lesson_id={lesson.id} | "
        f"lesson_number={lesson.lesson_number}"
    )

    return RedirectResponse(
        url=f"/lesson/{lesson.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/{lesson_id}")
async def lesson_exercise_page(
    request: Request,
    lesson_id: int,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Страница текущего упражнения."""
    info = await get_resume_info(db, user, lesson_id)
    lesson = info["lesson"]

    if info["completed"]:
        return RedirectResponse(
            url=f"/lesson/{lesson_id}/summary",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    exercise = info["exercise"]
    if not exercise:
        return RedirectResponse(
            url=f"/lesson/{lesson_id}/summary",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    return templates.TemplateResponse(
        "lesson/exercise.html",
        {
            "request": request,
            "user": user,
            "lesson": lesson,
            "exercise": exercise,
        },
    )


@router.post("/evaluate", dependencies=[Depends(require_csrf)])
async def lesson_evaluate_post(
    request: Request,
    exercise_id: int = Form(...),
    user_translation: str = Form(...),
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Оценка перевода.
    """
    is_htmx = bool(request.headers.get("HX-Request"))
    logger.info(f"📝 Оценка перевода | user_id={user.id} | exercise_id={exercise_id}")

    stmt_fallback = select(LessonExercise).where(LessonExercise.id == exercise_id)
    result_fallback = await db.execute(stmt_fallback)
    fallback_exercise = result_fallback.scalar_one_or_none()
    fallback_lesson_id = fallback_exercise.lesson_id if fallback_exercise else None

    try:
        result = await evaluate_exercise(
            db,
            user,
            exercise_id=exercise_id,
            user_translation=user_translation,
        )
    except LessonEvaluateError as e:
        logger.warning(f"⚠️ LessonEvaluateError: {e.code} - {e}")
        if is_htmx:
            return templates.TemplateResponse(
                "lesson/exercise_result.html",
                {"request": request, "user": user, "error": str(e)},
                status_code=422,
            )
        if e.code == "forbidden" or fallback_lesson_id is None:
            return _non_htmx_evaluate_error_redirect(None, str(e))
        if e.code == "lesson_completed":
            return _non_htmx_evaluate_error_redirect(
                fallback_lesson_id, str(e), to_summary=True, category="info",
            )
        return _non_htmx_evaluate_error_redirect(fallback_lesson_id, str(e))
    except GigaChatError as e:
        logger.error(
            f"🚨 GigaChatError during evaluation | Code: {e.code} | "
            f"Message: {e} | HTTP Status: {e.http_status}"
        )
        if is_htmx:
            return templates.TemplateResponse(
                "lesson/exercise_result.html",
                {
                    "request": request,
                    "user": user,
                    "error": "Сервис оценки временно недоступен. Попробуйте ещё раз.",
                },
                status_code=503,
            )
        return _non_htmx_evaluate_error_redirect(
            fallback_lesson_id,
            "Сервис оценки временно недоступен. Попробуйте ещё раз.",
        )

    logger.info(
        f"✅ Оценка завершена | exercise_id={exercise_id} | "
        f"status={result['evaluation']['status']}"
    )

    if not is_htmx:
        return _non_htmx_evaluate_success_redirect(result)

    return templates.TemplateResponse(
        "lesson/exercise_result.html",
        {
            "request": request,
            "user": user,
            **result,
        },
    )


@router.post("/suggestions/{exercise_id}/{word_index}", dependencies=[Depends(require_csrf)])
async def lesson_suggestion_action(
    request: Request,
    exercise_id: int,
    word_index: int,
    action: str = Form(...),
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Обработка подсказки (добавить/игнорировать)."""
    logger.info(
        f"💡 Обработка подсказки | exercise_id={exercise_id} | "
        f"word_index={word_index} | action={action}"
    )

    stmt = select(LessonExercise).where(LessonExercise.id == exercise_id)
    result = await db.execute(stmt)
    exercise = result.scalar_one_or_none()

    if not exercise:
        raise HTTPException(status_code=404, detail="Упражнение не найдено")

    stmt_lesson = select(Lesson).where(Lesson.id == exercise.lesson_id)
    result_lesson = await db.execute(stmt_lesson)
    lesson = result_lesson.scalar_one_or_none()

    if not lesson or lesson.user_id != user.id:
        raise HTTPException(status_code=403, detail="Доступ запрещён")

    suggested = list(exercise.suggested_words or [])
    if word_index >= len(suggested):
        raise HTTPException(status_code=404, detail="Подсказка не найдена")

    word_data = suggested[word_index]

    # ✅ ФИКС: Используем word_id, сохранённый при фильтрации,
    # вместо повторного поиска по lemma (который мог не учитывать pos).
    word_id = word_data.get("word_id")

    if action == "add":
        if word_id:
            # Проверяем, что запись ещё не создана (защита от повторного нажатия)
            stmt_uw = select(UserWord).where(
                UserWord.user_id == user.id,
                UserWord.word_id == word_id,
            )
            result_uw = await db.execute(stmt_uw)
            existing_uw = result_uw.scalar_one_or_none()

            if not existing_uw:
                uw = UserWord(
                    user_id=user.id,
                    word_id=word_id,
                    status="active",
                    stage=0,
                    due_lesson_number=user.last_lesson_number + 1,
                    source="suggestion",
                )
                db.add(uw)
            elif existing_uw.status == "ignored":
                existing_uw.status = "active"
                existing_uw.stage = 0
                existing_uw.due_lesson_number = user.last_lesson_number + 1
            # Если уже active или mastered — ничего не делаем
        else:
            # word_id отсутствует (не должно происходить после фильтрации,
            # но защищаемся от старых данных)
            logger.warning(
                f"[SUGGESTION] word_id missing for suggestion "
                f"exercise_id={exercise_id}, word_index={word_index}"
            )

        word_data["state"] = "added"

    elif action == "ignore":
        if word_id:
            stmt_uw = select(UserWord).where(
                UserWord.user_id == user.id,
                UserWord.word_id == word_id,
            )
            result_uw = await db.execute(stmt_uw)
            existing_uw = result_uw.scalar_one_or_none()

            if not existing_uw:
                uw = UserWord(
                    user_id=user.id,
                    word_id=word_id,
                    status="ignored",
                    stage=0,
                    source="suggestion",
                )
                db.add(uw)
            else:
                existing_uw.status = "ignored"

        word_data["state"] = "ignored"
    else:
        raise HTTPException(status_code=400, detail="Неизвестное действие")

    # ✅ ФИКС: Явно помечаем JSON-колонку как изменённую
    suggested[word_index] = word_data
    exercise.suggested_words = suggested
    flag_modified(exercise, "suggested_words")
    await db.flush()

    return templates.TemplateResponse(
        "lesson/_suggestion_card.html",
        {
            "request": request,
            "word": word_data,
            "word_index": word_index,
            "exercise_id": exercise_id,
        },
    )


@router.get("/{lesson_id}/summary")
async def lesson_summary_page(
    request: Request,
    lesson_id: int,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Итоги урока."""
    try:
        data = await get_lesson_summary(db, user, lesson_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Урок не найден")

    return templates.TemplateResponse(
        "lesson/summary.html",
        {
            "request": request,
            "user": user,
            **data,
        },
    )