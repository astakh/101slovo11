"""Тесты для app/utils/sentence_validation.py — валидация предложений."""
import pytest
from app.utils.sentence_validation import (
    validate_group_response,
    find_surface_form,
)


def _make_exercise(
    sentence: str = "I run every day.",
    translation: str = "Я бегаю каждый день.",
    target_words: list[dict] | None = None,
) -> dict:
    if target_words is None:
        target_words = [
            {"lemma": "run", "surface_form": "run", "pos": "verb"},
        ]
    return {
        "target_sentence": sentence,
        "reference_translation": translation,
        "target_words": target_words,
    }


class TestFindSurfaceForm:
    def test_found(self):
        assert find_surface_form("I run every day.", "run") == 2

    def test_case_insensitive(self):
        assert find_surface_form("I Run every day.", "run") == 2

    def test_not_found(self):
        assert find_surface_form("I walk every day.", "run") is None

    def test_empty_sentence(self):
        assert find_surface_form("", "run") is None

    def test_empty_form(self):
        assert find_surface_form("I run every day.", "") == 0


class TestValidateGroupResponseValid:
    def test_valid_exercise(self):
        exercises = [_make_exercise()]
        expected = [{"lemma": "run", "pos": "verb"}]
        errors = validate_group_response(exercises, expected)
        assert errors == []

    def test_multiple_valid_exercises(self):
        exercises = [
            _make_exercise(
                sentence="I run every day.",
                translation="Я бегаю каждый день.",
                target_words=[{"lemma": "run", "surface_form": "run", "pos": "verb"}],
            ),
            _make_exercise(
                sentence="She reads a book.",
                translation="Она читает книгу.",
                target_words=[{"lemma": "read", "surface_form": "reads", "pos": "verb"}],
            ),
        ]
        expected1 = [{"lemma": "run", "pos": "verb"}]
        expected2 = [{"lemma": "read", "pos": "verb"}]
        # validate_group_response принимает один набор expected для всех
        # Тестируем по одному
        errors1 = validate_group_response([exercises[0]], expected1)
        errors2 = validate_group_response([exercises[1]], expected2)
        assert errors1 == []
        assert errors2 == []


class TestValidateGroupResponseErrors:
    def test_empty_exercises(self):
        errors = validate_group_response([], [{"lemma": "run", "pos": "verb"}])
        assert len(errors) == 1
        assert "ни одного упражнения" in errors[0]

    def test_cyrillic_in_sentence(self):
        exercises = [_make_exercise(sentence="Я бегаю каждый день.")]
        expected = [{"lemma": "run", "pos": "verb"}]
        errors = validate_group_response(exercises, expected)
        assert any("кириллицу" in e for e in errors)

    def test_no_cyrillic_in_translation(self):
        exercises = [_make_exercise(translation="I run every day.")]
        expected = [{"lemma": "run", "pos": "verb"}]
        errors = validate_group_response(exercises, expected)
        assert any("кириллицу" in e for e in errors)

    def test_sentence_too_long(self):
        long_sentence = "I run " * 50  # > 200 символов
        exercises = [_make_exercise(sentence=long_sentence)]
        expected = [{"lemma": "run", "pos": "verb"}]
        errors = validate_group_response(exercises, expected)
        assert any("длиннее 200" in e for e in errors)

    def test_translation_too_long(self):
        long_translation = "Я бегаю " * 50  # > 300 символов
        exercises = [_make_exercise(translation=long_translation)]
        expected = [{"lemma": "run", "pos": "verb"}]
        errors = validate_group_response(exercises, expected)
        assert any("длиннее 300" in e for e in errors)

    def test_duplicate_sentences(self):
        exercises = [
            _make_exercise(),
            _make_exercise(),  # дубликат
        ]
        expected = [{"lemma": "run", "pos": "verb"}]
        errors = validate_group_response(exercises, expected)
        assert any("дублирующееся" in e for e in errors)

    def test_no_target_words(self):
        exercises = [_make_exercise(target_words=[])]
        expected = [{"lemma": "run", "pos": "verb"}]
        errors = validate_group_response(exercises, expected)
        assert any("нет target_words" in e for e in errors)

    def test_surface_form_not_found(self):
        exercises = [_make_exercise(
            sentence="I walk every day.",
            target_words=[{"lemma": "run", "surface_form": "run", "pos": "verb"}],
        )]
        expected = [{"lemma": "run", "pos": "verb"}]
        errors = validate_group_response(exercises, expected)
        assert any("не найдена" in e for e in errors)

    def test_empty_surface_form(self):
        exercises = [_make_exercise(
            target_words=[{"lemma": "run", "surface_form": "", "pos": "verb"}],
        )]
        expected = [{"lemma": "run", "pos": "verb"}]
        errors = validate_group_response(exercises, expected)
        assert any("пустая surface_form" in e for e in errors)

    def test_word_mismatch(self):
        exercises = [_make_exercise(
            target_words=[{"lemma": "walk", "surface_form": "run", "pos": "verb"}],
        )]
        expected = [{"lemma": "run", "pos": "verb"}]
        errors = validate_group_response(exercises, expected)
        assert any("несовпадение слов" in e for e in errors)

    def test_overlapping_surface_forms(self):
        # "run" — подстрока "running", обе найдутся на позиции 2 → пересечение
        exercises = [_make_exercise(
            sentence="I running every day.",
            target_words=[
                {"lemma": "run", "surface_form": "run", "pos": "verb"},
                {"lemma": "running", "surface_form": "running", "pos": "noun"},
            ],
        )]
        expected = [{"lemma": "run", "pos": "verb"}, {"lemma": "running", "pos": "noun"}]
        errors = validate_group_response(exercises, expected)
        assert any("пересекающиеся" in e for e in errors)


class TestValidateGroupResponseMultiWord:
    def test_two_words_valid(self):
        exercises = [_make_exercise(
            sentence="I run and jump.",
            translation="Я бегаю и прыгаю.",
            target_words=[
                {"lemma": "run", "surface_form": "run", "pos": "verb"},
                {"lemma": "jump", "surface_form": "jump", "pos": "verb"},
            ],
        )]
        expected = [
            {"lemma": "run", "pos": "verb"},
            {"lemma": "jump", "pos": "verb"},
        ]
        errors = validate_group_response(exercises, expected)
        assert errors == []