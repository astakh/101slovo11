"""Валидация предложений, сгенерированных LLM."""

import re
import unicodedata


# Паттерн кириллицы
_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF\u0500-\u052F]")


def find_surface_form(sentence: str, surface_form: str) -> int | None:
    """
    Ищет surface_form в предложении (регистронезависимо).

    Returns:
        Позиция начала или None.
    """
    lower_sentence = sentence.lower()
    lower_form = surface_form.lower()
    idx = lower_sentence.find(lower_form)
    if idx == -1:
        return None
    return idx


def _has_cyrillic(text: str) -> bool:
    """Проверяет наличие кириллицы."""
    return bool(_CYRILLIC_RE.search(text))


def _has_latin(text: str) -> bool:
    """Проверяет наличие латиницы."""
    return bool(re.search(r"[a-zA-Z]", text))


def validate_group_response(
    exercises: list[dict],
    expected_words: list[dict],
) -> list[str]:
    """
    Валидирует ответ LLM для группы слов.

    Args:
        exercises: список упражнений из ответа LLM.
        expected_words: список ожидаемых слов (lemma, pos).

    Returns:
        Список ошибок. Пустой список = всё ок.
    """
    errors: list[str] = []

    if not exercises:
        errors.append("LLM не вернул ни одного упражнения")
        return errors

    seen_sentences: set[str] = set()

    for i, ex in enumerate(exercises):
        prefix = f"Упражнение {i + 1}"

        sentence = ex.get("target_sentence", "")
        translation = ex.get("reference_translation", "")
        target_words = ex.get("target_words", [])

        # Длина предложения
        if len(sentence) > 200:
            errors.append(f"{prefix}: предложение длиннее 200 символов")

        # Длина перевода
        if len(translation) > 300:
            errors.append(f"{prefix}: перевод длиннее 300 символов")

        # Нет кириллицы в предложении
        if _has_cyrillic(sentence):
            errors.append(f"{prefix}: предложение содержит кириллицу")

        # Есть кириллица в переводе
        if not _has_cyrillic(translation):
            errors.append(f"{prefix}: перевод не содержит кириллицу")

        # Дубликаты предложений
        sentence_key = unicodedata.normalize("NFC", sentence.lower().strip())
        if sentence_key in seen_sentences:
            errors.append(f"{prefix}: дублирующееся предложение")
        seen_sentences.add(sentence_key)

        # Проверка target_words
        if not target_words:
            errors.append(f"{prefix}: нет target_words")
            continue

        # Множество (lemma, pos) должно совпадать с expected
        expected_set = {
            (w["lemma"].casefold(), w["pos"])
            for w in expected_words
        }
        actual_set = {
            (tw.get("lemma", "").casefold(), tw.get("pos", ""))
            for tw in target_words
        }

        if actual_set != expected_set:
            errors.append(
                f"{prefix}: несовпадение слов. "
                f"Ожидалось: {expected_set}, получено: {actual_set}"
            )

        # surface_form найдена в предложении
        for tw in target_words:
            sf = tw.get("surface_form", "")
            if not sf:
                errors.append(f"{prefix}: пустая surface_form для {tw.get('lemma')}")
                continue
            if find_surface_form(sentence, sf) is None:
                errors.append(
                    f"{prefix}: surface_form '{sf}' не найдена в предложении"
                )

        # Формы не пересекаются (позиции не перекрываются)
        positions: list[tuple[int, int]] = []
        for tw in target_words:
            sf = tw.get("surface_form", "")
            pos = find_surface_form(sentence, sf)
            if pos is not None:
                positions.append((pos, pos + len(sf)))

        positions.sort()
        for j in range(1, len(positions)):
            if positions[j][0] < positions[j - 1][1]:
                errors.append(f"{prefix}: пересекающиеся surface_form")
                break

    return errors