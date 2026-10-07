"""Кластеризация слов в группы для генерации предложений."""

import hashlib
import random


def _deterministic_shuffle(items: list, seed: str) -> list:
    """Детерминированная перетасовка на основе seed."""
    rng = random.Random(hashlib.sha256(seed.encode("utf-8")).hexdigest())
    shuffled = list(items)
    rng.shuffle(shuffled)
    return shuffled


def _compute_group_sizes(n: int) -> list[int]:
    """
    Вычисляет размеры групп.
    Группы по 1–3 слова, размеры отличаются не более чем на 1,
    меньшие группы первыми.
    """
    if n <= 0:
        return []
    if n <= 3:
        return [n]

    num_groups = (n + 2) // 3  # ceil(n / 3)
    base_size = n // num_groups
    remainder = n % num_groups

    sizes = []
    for i in range(num_groups):
        size = base_size + (1 if i < remainder else 0)
        sizes.append(size)

    # Сортируем по возрастанию (меньшие группы первыми)
    sizes.sort()
    return sizes


def cluster_words(
    words: list[dict],
    user_id: int,
    lesson_number: int,
) -> list[list[dict]]:
    """
    Разбивает слова на группы для генерации предложений.

    Args:
        words: список словарей с ключами word_id, lemma, pos, translations.
        user_id: ID пользователя (для seed).
        lesson_number: номер урока (для seed).

    Returns:
        Список групп. Каждая группа — список слов.
    """
    if not words:
        return []

    seed = f"{user_id}:{lesson_number}"
    shuffled = _deterministic_shuffle(words, seed)
    sizes = _compute_group_sizes(len(shuffled))

    groups: list[list[dict]] = []
    offset = 0
    for size in sizes:
        group = shuffled[offset:offset + size]
        groups.append(group)
        offset += size

    return groups