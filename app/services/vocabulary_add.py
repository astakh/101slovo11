# app/services/vocabulary_add.py
"""Сервис для поиска и добавления слов в словарь пользователя."""

import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.word import Word
from app.models.user_word import UserWord
from app.models.event import Event
from app.models.prompt import Prompt
from app.llm.gigachat import chat_json, GigaChatError
from app.llm.validation import EnrichWordResponse
from app.utils.text_validation import compute_lemma_key

logger = logging.getLogger(__name__)

VALID_POS = {
    "noun", "verb", "adjective", "adverb",
    "pronoun", "preposition", "conjunction", "interjection",
}
VALID_LEVELS = {"A1", "A2", "B1", "B2", "C1", "C2"}
VALID_DICTIONARIES = {"general", "it", "travel"}

# Только латиница, дефисы, пробелы, апострофы (для составных слов и сокращений)
_LEMMA_PATTERN = re.compile(r"^[a-zA-Z\s\-']+$")


def validate_lemma_input(lemma: str) -> str | None:
    """
    Валидирует входное слово.
    Возвращает текст ошибки или None если всё ок.
    """
    lemma = lemma.strip()
    if not lemma:
        return "Введите слово для поиска"
    if len(lemma) > 64:
        return "Слово слишком длинное (максимум 64 символа)"
    if len(lemma) < 2:
        return "Слово слишком короткое (минимум 2 символа)"
    if not _LEMMA_PATTERN.match(lemma):
        return "Используйте только латинские буквы, дефисы и пробелы"
    return None


async def search_word_in_db(db: AsyncSession, lemma: str) -> list[Word]:
    """Ищет слово в глобальной базе по lemma_key."""
    lemma_key = compute_lemma_key(lemma)
    stmt = select(Word).where(Word.lemma_key == lemma_key)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def enrich_word_via_llm(db: AsyncSession, lemma: str) -> list[dict]:
    """
    Вызывает LLM для получения данных о слове.
    Возвращает список вариантов (разные части речи).
    Может вернуть пустой список, если слово не существует.

    Raises:
        GigaChatError: при ошибке LLM.
    """
    stmt = select(Prompt).where(Prompt.key == "enrich_word")
    result = await db.execute(stmt)
    prompt = result.scalar_one_or_none()

    if not prompt:
        raise GigaChatError(
            "Промпт 'enrich_word' не найден. Запустите: python scripts/seed.py",
            code="llm_config_error",
        )

    system_message = prompt.system_template.replace("{word}", lemma)
    user_message = f"Слово: {lemma}"

    messages = [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]

    parsed, pt, ct, tt, lat = await chat_json(
        messages,
        temperature=0.3,
        max_tokens=2048,
        deadline_seconds=30.0,
    )

    logger.info(f"[LLM ENRICH] Raw: {parsed}")

    try:
        response = EnrichWordResponse.model_validate(parsed)
    except Exception as e:
        logger.error(f"[LLM ENRICH] Validation failed: {e}")
        raise GigaChatError(f"LLM response validation failed: {e}", code="llm_invalid_response")

    # Валидация и очистка данных
    variants = []
    for v in response.variants:
        pos = v.pos.strip().lower()
        if pos not in VALID_POS:
            logger.warning(f"[LLM ENRICH] Invalid pos '{v.pos}', skipping")
            continue

        if v.level not in VALID_LEVELS:
            logger.warning(f"[LLM ENRICH] Invalid level '{v.level}', skipping")
            continue

        translations = [t.strip() for t in v.translations if t.strip()]
        if not translations:
            logger.warning(f"[LLM ENRICH] Empty translations, skipping")
            continue

        # Валидация словарей
        dictionaries = [
            d.strip().lower()
            for d in v.dictionaries
            if d.strip().lower() in VALID_DICTIONARIES
        ]
        if not dictionaries:
            dictionaries = ["general"]

        variants.append({
            "lemma": v.lemma.strip(),
            "pos": pos,
            "level": v.level,
            "translations": translations,
            "dictionaries": dictionaries,
        })

    return variants


async def add_word_to_db(db: AsyncSession, word_data: dict) -> Word:
    """
    Добавляет слово в глобальную базу.
    Если слово уже существует (по lemma_key + pos), обновляет флаги словарей.
    """
    lemma_key = compute_lemma_key(word_data["lemma"])

    stmt = select(Word).where(Word.lemma_key == lemma_key, Word.pos == word_data["pos"])
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        # Обновляем флаги словарей (объединяем)
        dictionaries = word_data.get("dictionaries", ["general"])
        changed = False

        if "general" in dictionaries and not existing.in_general:
            existing.in_general = True
            changed = True
        if "it" in dictionaries and not existing.in_it:
            existing.in_it = True
            changed = True
        if "travel" in dictionaries and not existing.in_travel:
            existing.in_travel = True
            changed = True

        if len(word_data["translations"]) > len(existing.translations or []):
            existing.translations = word_data["translations"]
            changed = True

        if existing.level is None and word_data.get("level"):
            existing.level = word_data["level"]
            changed = True

        if changed:
            logger.info(f"[ADD WORD] Updated: {word_data['lemma']} ({word_data['pos']})")

        return existing

    # Создаём новое слово
    dictionaries = word_data.get("dictionaries", ["general"])
    word = Word(
        lemma=word_data["lemma"],
        lemma_key=lemma_key,
        pos=word_data["pos"],
        level=word_data["level"],
        translations=word_data["translations"],
        in_general="general" in dictionaries,
        in_it="it" in dictionaries,
        in_travel="travel" in dictionaries,
    )
    db.add(word)
    await db.flush()

    logger.info(f"[ADD WORD] Created: {word.lemma} ({word.pos}), id={word.id}, dicts={dictionaries}")
    return word


async def add_word_to_user(db: AsyncSession, user: User, word: Word) -> UserWord:
    """Добавляет слово в словарь пользователя."""
    stmt = select(UserWord).where(UserWord.user_id == user.id, UserWord.word_id == word.id)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        return existing

    user_word = UserWord(
        user_id=user.id,
        word_id=word.id,
        status="active",
        stage=0,
        due_lesson_number=user.last_lesson_number + 1,
        source="manual",
    )
    db.add(user_word)
    await db.flush()

    event = Event(user_id=user.id, type="word_added_manually", payload={"word_id": word.id})
    db.add(event)

    return user_word


async def search_and_enrich(
    db: AsyncSession,
    user: User,
    lemma: str,
) -> dict:
    """
    Основная функция: ищет слово в базе, если нет — генерирует через LLM
    и сразу добавляет в words.

    Returns:
        {
            "source": "db" | "generated",
            "words": [{"id": ..., "lemma": ..., "pos": ..., "level": ..., "translations": [...], "dictionaries": [...]}]
        }
    """
    # 1. Ищем в базе
    existing_words = await search_word_in_db(db, lemma)
    if existing_words:
        return {
            "source": "db",
            "words": [
                {
                    "id": w.id,
                    "lemma": w.lemma,
                    "pos": w.pos,
                    "level": w.level,
                    "translations": w.translations,
                    "dictionaries": _get_word_dictionaries(w),
                }
                for w in existing_words
            ],
        }

    # 2. Не найдено — генерируем через LLM
    variants = await enrich_word_via_llm(db, lemma)
    if not variants:
        return {"source": "generated", "words": []}

    # 3. Добавляем каждый вариант в words
    result_words = []
    for variant in variants:
        word = await add_word_to_db(db, variant)
        result_words.append({
            "id": word.id,
            "lemma": word.lemma,
            "pos": word.pos,
            "level": word.level,
            "translations": word.translations,
            "dictionaries": variant["dictionaries"],
        })

    return {
        "source": "generated",
        "words": result_words,
    }


def _get_word_dictionaries(word: Word) -> list[str]:
    """Извлекает список словарей из флагов слова."""
    dicts = []
    if word.in_general:
        dicts.append("general")
    if word.in_it:
        dicts.append("it")
    if word.in_travel:
        dicts.append("travel")
    return dicts or ["general"]