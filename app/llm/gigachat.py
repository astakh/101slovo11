"""Клиент GigaChat API с OAuth, ретраями и логированием."""

import asyncio
import json
import time
import uuid
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# OAuth URL остается прежним (с портом 9443)
OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"

# 🔥 ИСПРАВЛЕНИЕ: Современный унифицированный URL для чата (как в вашем примере)
CHAT_URL = "https://api.giga.chat/v1/chat/completions"

# Ретраи
MAX_RETRIES = 3
RETRY_DELAY_BASE = 1.0  # секунды
RETRYABLE_STATUS_CODES = {429, 500, 502, 503}


class GigaChatError(Exception):
    """Базовая ошибка GigaChat."""

    def __init__(self, message: str, code: str = "llm_error", http_status: int | None = None):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


class GigaTokenManager:
    """Управление OAuth-токеном GigaChat с ленивым обновлением."""

    def __init__(self):
        self._access_token: str | None = None
        self._expires_at: float = 0
        self._lock = asyncio.Lock()

    async def get_token(self) -> str:
        """Возвращает валидный access_token, обновляя при необходимости."""
        async with self._lock:
            now = time.time()
            # Обновляем токен, если он истекает менее чем через 2 минуты (120 сек)
            if self._access_token and now < self._expires_at - 120:
                return self._access_token

            await self._refresh_token()
            return self._access_token  # type: ignore

    async def _refresh_token(self) -> None:
        """Обновляет токен через OAuth."""
        auth_key = settings.GIGACHAT_AUTH_KEY
        if not auth_key or auth_key == "your-auth-key":
            raise GigaChatError("GIGACHAT_AUTH_KEY не настроен или равен заглушке", code="llm_config_error")

        payload = {"scope": settings.GIGACHAT_SCOPE}
        headers = {
            "Authorization": f"Bearer {auth_key}",
            "RqUID": str(uuid.uuid4()),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }

        logger.info(f"Запрос OAuth токена GigaChat на {OAUTH_URL}...")

        async with httpx.AsyncClient(verify=settings.GIGACHAT_VERIFY_SSL) as client:
            try:
                resp = await client.post(OAUTH_URL, data=payload, headers=headers, timeout=15.0)
            except httpx.ConnectError as e:
                logger.error(f"GigaChat OAuth: ConnectError. Проверьте порт 9443 и интернет. Детали: {e}")
                raise GigaChatError(f"Не удалось подключиться к серверу Сбера (порт 9443): {e}", code="llm_auth_connection_error")
            except httpx.HTTPError as e:
                logger.error(f"GigaChat OAuth: HTTPError - {e}")
                raise GigaChatError(f"Ошибка HTTP при запросе токена: {e}", code="llm_auth_error")

        if resp.status_code != 200:
            error_text = resp.text[:500]
            logger.error(f"GigaChat OAuth failed: HTTP {resp.status_code} - {error_text}")
            raise GigaChatError(
                f"OAuth failed: HTTP {resp.status_code} - {error_text}",
                code="llm_auth_failed",
                http_status=resp.status_code,
            )

        try:
            data = resp.json()
            self._access_token = data["access_token"]
            self._expires_at = float(data.get("expires_at", time.time() + 1800))
            logger.info("✅ OAuth токен GigaChat успешно получен.")
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            logger.error(f"GigaChat OAuth: Не удалось распарсить ответ. Ответ: {resp.text[:200]}")
            raise GigaChatError(f"Неверный формат ответа OAuth: {e}", code="llm_auth_parse_error")


# Глобальный менеджер токенов
_token_manager = GigaTokenManager()


async def chat(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.7,
    max_tokens: int = 5000,
    deadline_seconds: float = 45.0,
) -> dict:
    """Сырой вызов GigaChat API с ретраями."""
    token = await _token_manager.get_token()

    # Формируем payload строго как в примере из документации
    payload = {
        "model": settings.GIGACHAT_MODEL,
        "messages": messages,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
        "stream": False,
    }

    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        start_time = time.time()

        try:
            async with httpx.AsyncClient(verify=settings.GIGACHAT_VERIFY_SSL) as client:
                resp = await client.post(
                    CHAT_URL,
                    json=payload,
                    headers=headers,
                    timeout=deadline_seconds,
                )

            latency_ms = int((time.time() - start_time) * 1000)

            if resp.status_code == 200:
                data = resp.json()
                data["_latency_ms"] = latency_ms
                data["_attempt"] = attempt
                return data

            # Ретраи для временных ошибок
            if resp.status_code in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES:
                delay = RETRY_DELAY_BASE * (2 ** (attempt - 1))
                logger.warning(f"GigaChat API: {resp.status_code}, retry {attempt}/{MAX_RETRIES} in {delay}s")
                await asyncio.sleep(delay)
                if resp.status_code == 401:
                    token = await _token_manager.get_token()
                last_error = GigaChatError(
                    f"HTTP {resp.status_code}",
                    code="llm_http_error",
                    http_status=resp.status_code,
                )
                continue

            # Неустранимая ошибка
            error_text = resp.text[:300] if hasattr(resp, 'text') else ""
            logger.error(f"GigaChat API error: HTTP {resp.status_code} - {error_text}")
            raise GigaChatError(
                f"GigaChat API error: HTTP {resp.status_code} - {error_text}",
                code="llm_http_error",
                http_status=resp.status_code,
            )

        except httpx.TimeoutException:
            logger.error(f"GigaChat timeout (attempt {attempt})")
            last_error = GigaChatError("GigaChat timeout", code="llm_timeout")
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY_BASE * (2 ** (attempt - 1)))
                continue
            raise last_error

        except httpx.HTTPError as e:
            logger.error(f"GigaChat connection error: {e}")
            last_error = GigaChatError(f"GigaChat connection error: {e}", code="llm_connection_error")
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY_BASE * (2 ** (attempt - 1)))
                continue
            raise last_error

    raise last_error or GigaChatError("Unknown LLM error", code="llm_unknown")


def _extract_json(text: str) -> dict | list:
    """Извлекает JSON из текста ответа (с поддержкой markdown-блоков)."""
    text = text.strip()

    # Убираем markdown-обёртку если есть
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    return json.loads(text)


async def chat_json(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.7,
    max_tokens: int = 5000,
    deadline_seconds: float = 45.0,
    max_json_retries: int = 2,
) -> tuple[dict | list, int, int, int]:
    """Вызов GigaChat с извлечением JSON из ответа."""
    for json_attempt in range(max_json_retries + 1):
        response = await chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            deadline_seconds=deadline_seconds,
        )

        choices = response.get("choices", [])
        if not choices:
            raise GigaChatError("No choices in response", code="llm_empty_response")

        content = choices[0].get("message", {}).get("content", "")
        finish_reason = choices[0].get("finish_reason", "")

        usage = response.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        latency_ms = response.get("_latency_ms", 0)

        if finish_reason == "length" and json_attempt < max_json_retries:
            logger.warning("GigaChat: response truncated (length), retrying...")
            continue

        try:
            parsed = _extract_json(content)
            return parsed, prompt_tokens, completion_tokens, latency_ms
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"GigaChat: Invalid JSON (attempt {json_attempt}): {content[:200]}")
            if json_attempt < max_json_retries:
                messages = messages + [
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": "Ответь СТРОГО валидным JSON без markdown-блоков."},
                ]
                continue
            raise GigaChatError(
                f"Invalid JSON from LLM: {content[:200]}",
                code="llm_invalid_json",
            )

    raise GigaChatError("Max JSON retries exceeded", code="llm_invalid_json")