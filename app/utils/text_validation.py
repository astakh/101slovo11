"""Валидация пользовательского текста и лемм."""

import unicodedata
import re


# Управляющие символы, которые разрешены
_ALLOWED_CONTROL = {"\n", "\t"}


def validate_user_translation(text: str) -> str:
    """
    Валидирует и нормализует перевод пользователя.

    - NFC нормализация
    - trim
    - схлопывание пробелов
    - длина 1–500
    - удаление управляющих символов (кроме \\n, \\t)
    - удаление <<< и >>>

    Raises:
        ValueError: если текст невалиден.
    """
    if not text:
        raise ValueError("Перевод не может быть пустым")

    # NFC
    text = unicodedata.normalize("NFC", text)

    # Trim
    text = text.strip()

    # Удаление <<< и >>>
    text = text.replace("<<<", "").replace(">>>", "")

    # Удаление управляющих символов (кроме разрешённых)
    cleaned = []
    for ch in text:
        if unicodedata.category(ch).startswith("C") and ch not in _ALLOWED_CONTROL:
            continue
        cleaned.append(ch)
    text = "".join(cleaned)

    # Схлопывание пробелов (множественные пробелы → один)
    text = re.sub(r" {2,}", " ", text)

    # Trim после обработки
    text = text.strip()

    # Проверка длины
    if len(text) < 1:
        raise ValueError("Перевод не может быть пустым")
    if len(text) > 500:
        raise ValueError("Перевод слишком длинный (максимум 500 символов)")

    return text


def compute_lemma_key(lemma: str) -> str:
    """
    Вычисляет нормализованный ключ леммы.
    casefold(NFC(trim(lemma)))
    """
    normalized = unicodedata.normalize("NFC", lemma.strip())
    return normalized.casefold()


def normalize_for_comparison(text: str) -> str:
    """
    Нормализация для сравнения: NFC + lower + схлопывание пробелов.
    """
    text = unicodedata.normalize("NFC", text)
    text = text.lower()
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def validate_user_fragment(user_input: str, fragment: str) -> bool:
    """
    Проверяет, содержит ли пользовательский ввод указанный фрагмент.
    Сравнение регистронезависимое, с нормализацией.
    """
    normalized_input = normalize_for_comparison(user_input)
    normalized_fragment = normalize_for_comparison(fragment)
    return normalized_fragment in normalized_input