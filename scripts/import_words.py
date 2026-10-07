"""
Импорт слов из JSON-файла в таблицу `words`.

Использование:
    python scripts/import_words.py scripts/words_a1.json
    python scripts/import_words.py scripts/words_a1.json --dry-run
    python scripts/import_words.py scripts/words_a1.json --verbose

Формат JSON:
{
    "words": [
        {
            "lemma": "run",
            "pos": "verb",
            "level": "A1",
            "translations": ["бегать", "бежать"],
            "dictionaries": ["general", "travel"]
        }
    ]
}
"""

import argparse
import asyncio
import json
import sys
import unicodedata
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

# Добавляем корень проекта в sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import AsyncSessionLocal
from app.models.word import Word


# Валидные значения
VALID_POS = {
    "noun", "verb", "adjective", "adverb",
    "pronoun", "preposition", "conjunction", "interjection",
}
VALID_LEVELS = {"A1", "A2", "B1", "B2", "C1", "C2"}
VALID_DICTIONARIES = {"general", "it", "travel"}

# Маппинг словарь → колонка
DICT_FIELD_MAP = {
    "general": "in_general",
    "it": "in_it",
    "travel": "in_travel",
}


def compute_lemma_key(lemma: str) -> str:
    """casefold(NFC(trim(lemma)))"""
    normalized = unicodedata.normalize("NFC", lemma.strip())
    return normalized.casefold()


def validate_word(raw: dict, index: int) -> tuple[dict | None, list[str]]:
    """
    Валидирует одно слово.

    Returns:
        (очищенный словарь или None, список ошибок)
    """
    errors: list[str] = []

    # lemma
    lemma = raw.get("lemma", "")
    if not isinstance(lemma, str) or not lemma.strip():
        errors.append(f"[{index}] lemma: пустое или не строка")
        return None, errors
    lemma = lemma.strip()
    if len(lemma) > 64:
        errors.append(f"[{index}] lemma: длиннее 64 символов")
        return None, errors

    # pos
    pos = raw.get("pos", "")
    if pos not in VALID_POS:
        errors.append(f"[{index}] pos '{pos}': недопустимое значение. Допустимые: {VALID_POS}")
        return None, errors

    # level
    level = raw.get("level", "")
    if level not in VALID_LEVELS:
        errors.append(f"[{index}] level '{level}': недопустимое значение. Допустимые: {VALID_LEVELS}")
        return None, errors

    # translations
    translations = raw.get("translations", [])
    if not isinstance(translations, list) or not translations:
        errors.append(f"[{index}] translations: должен быть непустой массив")
        return None, errors
    if len(translations) > 5:
        errors.append(f"[{index}] translations: больше 5 элементов")
        return None, errors
    # Проверяем каждый перевод
    clean_translations = []
    for t in translations:
        if not isinstance(t, str) or not t.strip():
            errors.append(f"[{index}] translations: элемент не строка или пустой")
            return None, errors
        clean_translations.append(t.strip())

    # dictionaries
    dictionaries = raw.get("dictionaries", ["general"])
    if not isinstance(dictionaries, list):
        errors.append(f"[{index}] dictionaries: должен быть массив")
        return None, errors
    clean_dicts = []
    for d in dictionaries:
        if d in VALID_DICTIONARIES:
            clean_dicts.append(d)
        else:
            errors.append(f"[{index}] dictionaries: неизвестный словарь '{d}'")
            return None, errors
    if not clean_dicts:
        errors.append(f"[{index}] dictionaries: пустой список")
        return None, errors

    return {
        "lemma": lemma,
        "lemma_key": compute_lemma_key(lemma),
        "pos": pos,
        "level": level,
        "translations": clean_translations,
        "dictionaries": clean_dicts,
    }, errors


async def import_words(
    file_path: str,
    dry_run: bool = False,
    verbose: bool = False,
) -> None:
    """Импортирует слова из JSON-файла в БД."""

    # Читаем файл
    path = Path(file_path)
    if not path.exists():
        print(f"❌ Файл не найден: {file_path}")
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"❌ Ошибка парсинга JSON: {e}")
            sys.exit(1)

    raw_words = data.get("words", [])
    if not raw_words:
        print("⚠️ В файле нет слов (ключ 'words' пуст или отсутствует)")
        return

    print(f"📂 Файл: {file_path}")
    print(f"📊 Слов в файле: {len(raw_words)}")

    # Валидация
    valid_words: list[dict] = []
    all_errors: list[str] = []

    for i, raw in enumerate(raw_words):
        cleaned, errors = validate_word(raw, i)
        if errors:
            all_errors.extend(errors)
        elif cleaned:
            valid_words.append(cleaned)

    if all_errors:
        print(f"\n⚠️ Ошибки валидации ({len(all_errors)}):")
        for err in all_errors:
            print(f"   {err}")

    if not valid_words:
        print("❌ Нет валидных слов для импорта")
        return

    print(f"✅ Валидных слов: {len(valid_words)}")

    if dry_run:
        print("\n🔍 DRY RUN — записи в БД не будет.")
        print("Слова для вставки:")
        for w in valid_words[:10]:
            print(f"   {w['lemma']} ({w['pos']}, {w['level']}) → {w['dictionaries']}")
        if len(valid_words) > 10:
            print(f"   ... и ещё {len(valid_words) - 10}")
        return

    # Импорт в БД
    async with AsyncSessionLocal() as session:
        created = 0
        updated = 0
        skipped = 0

        for w in valid_words:
            # Проверяем существование
            stmt = select(Word).where(
                Word.lemma_key == w["lemma_key"],
                Word.pos == w["pos"],
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                # Обновляем существующее слово:
                # добавляем флаги словарей, обновляем переводы/уровень
                changed = False

                for d in w["dictionaries"]:
                    field = DICT_FIELD_MAP[d]
                    if not getattr(existing, field):
                        setattr(existing, field, True)
                        changed = True

                # Обновляем переводы, если текущие пустые или новые богаче
                if len(w["translations"]) > len(existing.translations or []):
                    existing.translations = w["translations"]
                    changed = True

                # Обновляем уровень, если он был None
                if existing.level is None and w["level"]:
                    existing.level = w["level"]
                    changed = True

                if changed:
                    updated += 1
                    if verbose:
                        print(f"   🔄 Обновлено: {w['lemma']} ({w['pos']})")
                else:
                    skipped += 1
                    if verbose:
                        print(f"   ⏭ Пропущено: {w['lemma']} ({w['pos']})")
            else:
                # Создаём новое слово
                word = Word(
                    lemma=w["lemma"],
                    lemma_key=w["lemma_key"],
                    pos=w["pos"],
                    level=w["level"],
                    translations=w["translations"],
                    in_general="general" in w["dictionaries"],
                    in_it="it" in w["dictionaries"],
                    in_travel="travel" in w["dictionaries"],
                )
                session.add(word)
                created += 1
                if verbose:
                    print(f"   ➕ Создано: {w['lemma']} ({w['pos']}, {w['level']})")

        await session.commit()

    print(f"\n🎉 Импорт завершён!")
    print(f"   Создано: {created}")
    print(f"   Обновлено: {updated}")
    print(f"   Пропущено: {skipped}")


def main():
    parser = argparse.ArgumentParser(
        description="Импорт слов из JSON в словарь 101slovo"
    )
    parser.add_argument(
        "file",
        help="Путь к JSON-файлу со словами",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только валидация, без записи в БД",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Подробный вывод по каждому слову",
    )
    args = parser.parse_args()

    asyncio.run(import_words(args.file, dry_run=args.dry_run, verbose=args.verbose))


if __name__ == "__main__":
    main()