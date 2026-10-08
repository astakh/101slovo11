"""Высокоуровневые функции для генерации и оценки."""

import uuid
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.models.prompt import Prompt
from app.llm.gigachat import chat_json, GigaChatError
from app.llm.validation import GenerateResponse, EvaluateResponse, LlmUsage

logger = logging.getLogger(__name__)


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

    parsed, prompt_tokens, completion_tokens, total_tokens, _ = await chat_json(
        messages,
        temperature=settings.GEN_TEMPERATURE,
        max_tokens=2048,
        deadline_seconds=45.0,
    )

    try:
        response = GenerateResponse.model_validate(parsed)
    except Exception as e:
        raise GigaChatError(
            f"LLM response validation failed: {e}",
            code="llm_invalid_response",
        )

    usage = LlmUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
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
    """
    system_template = await _get_prompt_template(db, "evaluate_translation")
    eval_uuid = uuid.uuid4().hex[:16]

    import json
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

    parsed, prompt_tokens, completion_tokens, total_tokens, _ = await chat_json(
        messages,
        temperature=settings.EVAL_TEMPERATURE,
        max_tokens=1024,
        deadline_seconds=15.0,
    )

    # 🔥 ЛОГИРОВАНИЕ: Сырой ответ от LLM до валидации
    logger.info(f"[LLM EVAL] Raw parsed response: {json.dumps(parsed, ensure_ascii=False, indent=2)}")

    try:
        response = EvaluateResponse.model_validate(parsed)
    except Exception as e:
        logger.error(f"[LLM EVAL] Pydantic validation failed: {e}")
        raise GigaChatError(
            f"LLM evaluation validation failed: {e}",
            code="llm_invalid_response",
        )

    # 🔥 ЛОГИРОВАНИЕ: Извлеченные подсказки после валидации
    logger.info(f"[LLM EVAL] Validated suggested_words count: {len(response.suggested_words)}")
    if response.suggested_words:
        logger.info(f"[LLM EVAL] Suggested words data: {response.suggested_words}")

    usage = LlmUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )

    return response.model_dump(), usage