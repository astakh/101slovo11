"""Детерминированное ранжирование слов."""

import hashlib


def rank_words(words: list[dict], seed: str) -> list[dict]:
    """
    Детерминированное ранжирование слов на основе seed.
    Используется для стабильного порядка при выборе новых слов.

    Args:
        words: список слов.
        seed: строка-сид (например, f"{user_id}:{lesson_number}").

    Returns:
        Отсортированный список слов.
    """
    if not words:
        return []

    seed_hash = hashlib.sha256(seed.encode("utf-8")).hexdigest()

    def sort_key(word: dict) -> str:
        word_id = word.get("word_id", word.get("id", 0))
        return hashlib.sha256(f"{seed_hash}:{word_id}".encode("utf-8")).hexdigest()

    return sorted(words, key=sort_key)