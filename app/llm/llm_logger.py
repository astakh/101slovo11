"""Логирование вызовов LLM в таблицу llm_calls."""

from sqlalchemy.ext.asyncio import AsyncSession
from app.models.llm_call import LlmCall


async def log_llm_call(
    db: AsyncSession,
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
    """Записывает вызов LLM в лог."""
    call = LlmCall(
        purpose=purpose,
        user_id=user_id,
        lesson_id=lesson_id,
        exercise_id=exercise_id,
        attempt=attempt,
        request=request or {},
        response_raw=response_raw,
        response_json=response_json,
        status=status,
        http_status=http_status,
        latency_ms=latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        error_code=error_code,
    )
    db.add(call)
    # Не коммитим — коммит произойдёт в рамках основной транзакции