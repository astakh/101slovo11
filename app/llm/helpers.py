"""Высокоуровневые функции для генерации и оценки."""

import json
import uuid
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.prompt import Prompt
from app.db import AsyncSessionLocal
from app.llm.gigachat import chat_json, GigaChatError
from app.llm.validation import GenerateResponse, EvaluateResponse, LlmUsage
from app.llm.llm_logger import log_llm_call
from app.utils.sentence_validation import validate_group_response

logger = logging.getLogger(__name__)

# Максимум повторных запросов при невалидном ответе (не считая первого).
# Итого максимум 2 попытки: основная + 1 ретрай.
MAX_VALIDATION_RETRIES = 1


async def _log_llm_call_safe(
    *,
    purpose: str,
    user_id: int | None = None,
    lesson_id: int | None = None,
    exercise_id: int | None = None,
    attempt: int = 1,
    request: dict | None = None,
    response_raw: str | None = None,
    response_json: dict | None = None,
    status: str = "ok",
    http_status: int | None = None,
    latency_ms: int | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    error_code: str | None = None,
) -> None:
    """
    Безопасное логирование вызова LLM в отдельной транзакции.

    Используется для записи невалидных ответов, которые не должны
    теряться при откате основной транзакции (например, если после
    логирования бросается исключение и сессия откатывается).

    Не бросает исключений при ошибке логирования — только предупреждение.
    """
    try:
        async with AsyncSessionLocal() as session:
            await log_llm_call(
                session,
                purpose=purpose,
                user_id=user_id,
                lesson_id=lesson_id,
                exercise_id=exercise_id,
                attempt=attempt,
                request=request,
                response_raw=response_raw,
                response_json=response_json,
                status=status,
                http_status=http_status,
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                error_code=error_code,
            )
            await session.commit()
    except Exception as e:
        logger.warning(f"[LLM LOG] Failed to log LLM call: {e}")


async def _get_prompt_template(db: AsyncSession, key: str) -> str:
    """Загружает шаблон промпта из БД."""
    stmt = select(Prompt).where(Prompt.key == key)
    result = await db.execute(stmt)
    prompt = result.scalar_one_or_none()
    if not prompt:
        raise GigaChatError(f"Prompt '{key}' not found in DB", code="llm_config_error")
    return prompt.system_template


async def generate_sentences(
    db: AsyncSession,
    *,
    level: str,
    word_groups: list[list[dict]],
    user_id: int,
) -> tuple[list[dict], LlmUsage]:
    """
    Генерирует предложения для урока через LLM.

    Валидация:
    - Структура ответа (Pydantic).
    - Количество упражнений == количеству групп слов.
    - Каждое предложение проходит проверку через validate_group_response
      (кириллица, длина, дубликаты, наличие слов, пересечение форм).

    При невалидном ответе — 1 повторный запрос с корректирующим сообщением.
    Невалидные ответы логируются в таблицу `llm_calls`.
    """
    system_template = await _get_prompt_template(db, "generate_sentences")
    system_message = system_template.replace("{level}", level)

    words_lines = []
    for group_idx, group in enumerate(word_groups, 1):
        words_in_group = []
        for w in group:
            translations = ", ".join(w.get("translations", []))
            words_in_group.append(f"{w['lemma']} ({w['pos']}) — {translations}")
        words_lines.append(f"Группа {group_idx}: {'; '.join(words_in_group)}")

    user_message = (
        f"Сгенерируй по одному предложению для каждой группы слов.\n"
        f"Всего групп: {len(word_groups)}.\n"
        + "\n".join(words_lines)
    )

    messages = [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]

    response: GenerateResponse | None = None
    usage_data: tuple[int, int, int, int] | None = None  # (pt, ct, tt, latency_ms)
    final_attempt = 1

    for validation_attempt in range(MAX_VALIDATION_RETRIES + 1):
        final_attempt = validation_attempt + 1
        attempt_request_messages = list(messages)

        parsed, prompt_tokens, completion_tokens, total_tokens, latency_ms = await chat_json(
            messages,
            temperature=settings.GEN_TEMPERATURE,
            max_tokens=4096,
            deadline_seconds=60.0,
        )
        usage_data = (prompt_tokens, completion_tokens, total_tokens, latency_ms)

        # ── 1. Pydantic валидация ──────────────────────────────
        try:
            response = GenerateResponse.model_validate(parsed)
        except Exception as e:
            error_msg = f"Pydantic validation failed: {e}"
            logger.error(f"[LLM GEN] {error_msg}")

            await _log_llm_call_safe(
                purpose="generate",
                user_id=user_id,
                attempt=final_attempt,
                request={"messages": attempt_request_messages},
                response_json=parsed if isinstance(parsed, dict) else None,
                status="invalid_response",
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                error_code="llm_invalid_response",
            )

            if validation_attempt < MAX_VALIDATION_RETRIES:
                messages = messages + [
                    {"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)},
                    {
                        "role": "user",
                        "content": (
                            f"Ответ не прошёл проверку структуры: {error_msg}. "
                            "Исправь и верни ТОЛЬКО валидный JSON."
                        ),
                    },
                ]
                continue

            raise GigaChatError(
                f"LLM response validation failed: {e}",
                code="llm_invalid_response",
            )

        # ── 2. Проверка количества упражнений ──────────────────
        if len(response.exercises) != len(word_groups):
            error_msg = (
                f"Ожидалось {len(word_groups)} упражнений, "
                f"получено {len(response.exercises)}"
            )
            logger.error(f"[LLM GEN] {error_msg}")

            await _log_llm_call_safe(
                purpose="generate",
                user_id=user_id,
                attempt=final_attempt,
                request={"messages": attempt_request_messages},
                response_json=parsed if isinstance(parsed, dict) else None,
                status="invalid_response",
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                error_code="llm_wrong_count",
            )

            if validation_attempt < MAX_VALIDATION_RETRIES:
                messages = messages + [
                    {"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)},
                    {
                        "role": "user",
                        "content": (
                            f"Ошибка: {error_msg}. "
                            f"Сгенерируй ровно {len(word_groups)} упражнений. "
                            "Верни ТОЛЬКО валидный JSON."
                        ),
                    },
                ]
                continue

            raise GigaChatError(
                f"LLM returned wrong number of exercises: {error_msg}",
                code="llm_invalid_response",
            )

        # ── 3. Валидация предложений ───────────────────────────
        all_validation_errors: list[str] = []
        for i, ex in enumerate(response.exercises):
            group = word_groups[i]
            errors = validate_group_response([ex.model_dump()], group)
            all_validation_errors.extend(errors)

        if all_validation_errors:
            logger.error(f"[LLM GEN] Validation errors: {all_validation_errors}")

            await _log_llm_call_safe(
                purpose="generate",
                user_id=user_id,
                attempt=final_attempt,
                request={"messages": attempt_request_messages},
                response_json=parsed if isinstance(parsed, dict) else None,
                status="invalid_response",
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                error_code="llm_validation_failed",
            )

            if validation_attempt < MAX_VALIDATION_RETRIES:
                error_summary = "; ".join(all_validation_errors[:5])
                messages = messages + [
                    {"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)},
                    {
                        "role": "user",
                        "content": (
                            f"Ответ не прошёл проверку: {error_summary}. "
                            "Исправь и верни ТОЛЬКО валидный JSON."
                        ),
                    },
                ]
                continue

            raise GigaChatError(
                f"LLM sentence validation failed: {'; '.join(all_validation_errors[:3])}",
                code="llm_invalid_response",
            )

        # Все проверки прошли — выходим из цикла
        break

    if response is None:
        raise GigaChatError(
            "Max validation retries exceeded",
            code="llm_invalid_response",
        )

    usage = LlmUsage(
        prompt_tokens=usage_data[0],
        completion_tokens=usage_data[1],
        total_tokens=usage_data[2],
    )

    # Логирование успешного вызова (без полного запроса для экономии места)
    await _log_llm_call_safe(
        purpose="generate",
        user_id=user_id,
        attempt=final_attempt,
        response_json=response.model_dump(),
        status="ok",
        latency_ms=usage_data[3],
        prompt_tokens=usage_data[0],
        completion_tokens=usage_data[1],
    )

    exercises = [ex.model_dump() for ex in response.exercises]
    return exercises, usage


async def evaluate_translation(
    db: AsyncSession,
    *,
    target_sentence: str,
    reference_translation: str,
    target_words: list[dict],
    user_translation: str,
    user_id: int,
) -> tuple[dict, LlmUsage]:
    """
    Оценивает перевод пользователя через LLM.

    Валидация:
    - Структура ответа (Pydantic).
    - Полнота: все целевые слова должны быть в `evaluations`.
      Если после ретрая слова всё ещё отсутствуют — продолжаем
      с неполной оценкой (лучше неполная оценка, чем блокировка).

    При невалидном ответе — 1 повторный запрос с корректирующим сообщением.
    Невалидные ответы логируются в таблицу `llm_calls`.
    """
    system_template = await _get_prompt_template(db, "evaluate_translation")
    eval_uuid = uuid.uuid4().hex[:16]

    target_words_json = json.dumps(target_words, ensure_ascii=False)
    system_message = (
        system_template
        .replace("{target_sentence}", target_sentence)
        .replace("{reference_translation}", reference_translation)
        .replace("{target_words_json}", target_words_json)
        .replace("{uuid}", eval_uuid)
    )
    user_message = f"<<<UT_{eval_uuid}>>>{user_translation}<<<UT_{eval_uuid}>>>"

    messages = [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]

    response: EvaluateResponse | None = None
    usage_data: tuple[int, int, int, int] | None = None
    final_attempt = 1

    for validation_attempt in range(MAX_VALIDATION_RETRIES + 1):
        final_attempt = validation_attempt + 1
        attempt_request_messages = list(messages)

        parsed, prompt_tokens, completion_tokens, total_tokens, latency_ms = await chat_json(
            messages,
            temperature=settings.EVAL_TEMPERATURE,
            max_tokens=2048,
            deadline_seconds=30.0,
        )
        usage_data = (prompt_tokens, completion_tokens, total_tokens, latency_ms)

        logger.info(
            f"[LLM EVAL] Raw parsed response: "
            f"{json.dumps(parsed, ensure_ascii=False, indent=2)}"
        )

        # ── 1. Pydantic валидация ──────────────────────────────
        try:
            response = EvaluateResponse.model_validate(parsed)
        except Exception as e:
            error_msg = f"Pydantic validation failed: {e}"
            logger.error(f"[LLM EVAL] {error_msg}")

            await _log_llm_call_safe(
                purpose="evaluate",
                user_id=user_id,
                attempt=final_attempt,
                request={"messages": attempt_request_messages},
                response_json=parsed if isinstance(parsed, dict) else None,
                status="invalid_response",
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                error_code="llm_invalid_response",
            )

            if validation_attempt < MAX_VALIDATION_RETRIES:
                messages = messages + [
                    {"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)},
                    {
                        "role": "user",
                        "content": (
                            f"Ответ не прошёл проверку структуры: {error_msg}. "
                            "Исправь и верни ТОЛЬКО валидный JSON."
                        ),
                    },
                ]
                continue

            raise GigaChatError(
                f"LLM evaluation validation failed: {e}",
                code="llm_invalid_response",
            )

        # ── 2. Проверка полноты оценки ─────────────────────────
        evaluated_lemmas = {e.lemma.casefold() for e in response.evaluations}
        target_lemmas = {tw.get("lemma", "").casefold() for tw in target_words}
        missing_lemmas = target_lemmas - evaluated_lemmas

        if missing_lemmas:
            error_msg = (
                f"Оценка не содержит все целевые слова. "
                f"Отсутствуют: {', '.join(sorted(missing_lemmas))}"
            )
            logger.error(f"[LLM EVAL] {error_msg}")

            await _log_llm_call_safe(
                purpose="evaluate",
                user_id=user_id,
                attempt=final_attempt,
                request={"messages": attempt_request_messages},
                response_json=parsed if isinstance(parsed, dict) else None,
                status="invalid_response",
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                error_code="llm_incomplete_evaluations",
            )

            if validation_attempt < MAX_VALIDATION_RETRIES:
                messages = messages + [
                    {"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)},
                    {
                        "role": "user",
                        "content": (
                            f"Ошибка: {error_msg}. "
                            "Включи оценки для ВСЕХ целевых слов. "
                            "Верни ТОЛЬКО валидный JSON."
                        ),
                    },
                ]
                continue

            # Последняя попытка: продолжаем с неполной оценкой.
            # В lesson_evaluate.py отсутствующие слова получат статус "learning".
            logger.warning(
                f"[LLM EVAL] Proceeding with incomplete evaluations. "
                f"Missing: {missing_lemmas}"
            )

        # Все проверки прошли — выходим из цикла
        break

    if response is None:
        raise GigaChatError(
            "Max validation retries exceeded",
            code="llm_invalid_response",
        )

    logger.info(
        f"[LLM EVAL] Validated suggested_words count: "
        f"{len(response.suggested_words)}"
    )
    if response.suggested_words:
        logger.info(f"[LLM EVAL] Suggested words data: {response.suggested_words}")

    usage = LlmUsage(
        prompt_tokens=usage_data[0],
        completion_tokens=usage_data[1],
        total_tokens=usage_data[2],
    )

    # Логирование успешного вызова
    await _log_llm_call_safe(
        purpose="evaluate",
        user_id=user_id,
        attempt=final_attempt,
        response_json=response.model_dump(),
        status="ok",
        latency_ms=usage_data[3],
        prompt_tokens=usage_data[0],
        completion_tokens=usage_data[1],
    )

    return response.model_dump(), usage