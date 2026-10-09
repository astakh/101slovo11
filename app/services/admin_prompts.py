"""Сервис для управления промптами (админ)."""
import re
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.prompt import Prompt
from app.models.event import Event
from app.models.user import User

ALLOWED_KEYS = {"generate_sentences", "evaluate_translation", "enrich_word"}

# Обязательные плейсхолдеры для каждого ключа.
# Для evaluate_translation плейсхолдеры требуются, т.к. они подставляются в helpers.py.
# Для enrich_word плейсхолдер {word} подставляется в vocabulary_add.py.
REQUIRED_PLACEHOLDERS = {
    "generate_sentences": {"{level}"},
    "evaluate_translation": {
        "{target_sentence}",
        "{reference_translation}",
        "{target_words_json}",
        "{uuid}",
    },
    "enrich_word": {"{word}"},
}

# Все допустимые плейсхолдеры (чтобы не было лишних).
ALLOWED_PLACEHOLDERS = {
    "generate_sentences": {"{level}"},
    "evaluate_translation": {
        "{target_sentence}",
        "{reference_translation}",
        "{target_words_json}",
        "{uuid}",
    },
    "enrich_word": {"{word}"},
}


def validate_prompt_template(key: str, template: str) -> list[str]:
    """
    Валидирует шаблон промпта.

    Правила:
    - Длина 1–8000.
    - Обязательные плейсхолдеры присутствуют.
    - Нет недопустимых плейсхолдеров.
    - Тестовый рендеринг проходит без ошибок.

    Returns:
        Список ошибок. Пустой список = всё ок.
    """
    errors: list[str] = []

    if key not in ALLOWED_KEYS:
        errors.append(f"Неизвестный ключ промпта: {key}")
        return errors

    # Длина
    if len(template) < 1:
        errors.append("Шаблон не может быть пустым")
        return errors
    if len(template) > 8000:
        errors.append("Шаблон слишком длинный (максимум 8000 символов)")
        return errors

    # Поиск плейсхолдеров вида {something}
    found = set(re.findall(r"\{[a-zA-Z_]+\}", template))
    required = REQUIRED_PLACEHOLDERS.get(key, set())
    allowed = ALLOWED_PLACEHOLDERS.get(key, set())

    # Обязательные плейсхолдеры
    missing = required - found
    if missing:
        errors.append(
            f"Отсутствуют обязательные плейсхолдеры: {', '.join(sorted(missing))}"
        )

    # Лишние плейсхолдеры
    extra = found - allowed
    if extra:
        errors.append(
            f"Недопустимые плейсхолдеры: {', '.join(sorted(extra))}"
        )

    # Проверка рендеринга с тестовыми значениями
    test_values = {
        "level": "A1",
        "target_sentence": "Test sentence.",
        "reference_translation": "Тестовый перевод.",
        "target_words_json": "[]",
        "uuid": "testuuid123",
        "word": "run",
    }

    try:
        rendered = template
        for k, v in test_values.items():
            rendered = rendered.replace("{" + k + "}", v)

        # После замены не должно остаться незаполненных плейсхолдеров
        remaining = re.findall(r"\{[a-zA-Z_]+\}", rendered)
        if remaining:
            errors.append(
                f"После рендеринга остались незаполненные плейсхолдеры: "
                f"{', '.join(remaining)}"
            )
    except Exception as e:
        errors.append(f"Ошибка рендеринга шаблона: {e}")

    return errors


async def get_all_prompts(db: AsyncSession) -> list[Prompt]:
    """Возвращает все промпты, отсортированные по ключу."""
    stmt = select(Prompt).order_by(Prompt.key.asc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_prompt(db: AsyncSession, key: str) -> Prompt | None:
    """Возвращает промпт по ключу или None."""
    stmt = select(Prompt).where(Prompt.key == key)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def update_prompt(
    db: AsyncSession,
    key: str,
    template: str,
    admin: User,
) -> Prompt:
    """
    Обновляет промпт и записывает событие.

    Raises:
        ValueError: если промпт не найден.
    """
    stmt = select(Prompt).where(Prompt.key == key)
    result = await db.execute(stmt)
    prompt = result.scalar_one_or_none()

    if not prompt:
        raise ValueError(f"Промпт '{key}' не найден")

    prompt.system_template = template
    prompt.updated_by = admin.id

    event = Event(
        user_id=admin.id,
        type="prompt_updated",
        payload={"key": key},
    )
    db.add(event)

    await db.flush()
    await db.refresh(prompt)
    return prompt