"""Тесты для app/utils/text_validation.py — валидация текста."""
import unicodedata
import pytest
from app.utils.text_validation import (
    validate_user_translation,
    compute_lemma_key,
    normalize_for_comparison,
    validate_user_fragment,
)


class TestValidateUserTranslation:
    def test_valid_translation(self):
        result = validate_user_translation("Это тестовый перевод")
        assert result == "Это тестовый перевод"

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="пустым"):
            validate_user_translation("")

    def test_none_raises(self):
        with pytest.raises((ValueError, TypeError)):
            validate_user_translation(None)

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="пустым"):
            validate_user_translation("   ")

    def test_too_long_raises(self):
        long_text = "а" * 501
        with pytest.raises(ValueError, match="длинный"):
            validate_user_translation(long_text)

    def test_exactly_500_ok(self):
        text = "а" * 500
        result = validate_user_translation(text)
        assert len(result) == 500

    def test_strips_control_chars(self):
        """Управляющие символы (кроме \n и \t) удаляются."""
        text = "Привет\x00\x01Мир"
        result = validate_user_translation(text)
        assert "\x00" not in result
        assert "\x01" not in result
        assert "Привет" in result
        assert "Мир" in result

    def test_keeps_newline_and_tab(self):
        """\n и \t разрешены."""
        text = "Строка1\nСтрока2\tТабуляция"
        result = validate_user_translation(text)
        assert "\n" in result
        assert "\t" in result

    def test_removes_angle_brackets(self):
        text = "<<<Тестовый>>> перевод"
        result = validate_user_translation(text)
        assert "<<<" not in result
        assert ">>>" not in result
        assert "Тестовый" in result
        assert "перевод" in result

    def test_collapses_spaces(self):
        text = "Привет    мир     тут"
        result = validate_user_translation(text)
        assert "  " not in result
        assert result == "Привет мир тут"

    def test_nfc_normalization(self):
        # é как e + combining accent vs. один символ
        decomposed = "e\u0301"  # e + combining acute
        text = f"test {decomposed}"
        result = validate_user_translation(text)
        expected = unicodedata.normalize("NFC", text)
        assert result == expected.strip()


class TestComputeLemmaKey:
    def test_lowercase(self):
        assert compute_lemma_key("Run") == "run"

    def test_already_lowercase(self):
        assert compute_lemma_key("run") == "run"

    def test_strips_whitespace(self):
        assert compute_lemma_key("  run  ") == "run"

    def test_nfc_normalization(self):
        decomposed = "e\u0301"  # e + combining acute
        result = compute_lemma_key(decomposed)
        expected = unicodedata.normalize("NFC", decomposed).casefold()
        assert result == expected

    def test_casefold(self):
        # Немецкое ß → ss (стандарт Unicode CaseFolding)
        assert compute_lemma_key("Straße") == "strasse"

class TestNormalizeForComparison:
    def test_lowercase(self):
        assert normalize_for_comparison("Hello World") == "hello world"

    def test_collapses_spaces(self):
        assert normalize_for_comparison("Hello   World") == "hello world"

    def test_nfc(self):
        decomposed = "e\u0301"
        result = normalize_for_comparison(decomposed)
        expected = unicodedata.normalize("NFC", decomposed).lower()
        assert result == expected


class TestValidateUserFragment:
    def test_contains_fragment(self):
        assert validate_user_fragment("Привет мир", "мир") is True

    def test_case_insensitive(self):
        assert validate_user_fragment("Привет Мир", "мир") is True

    def test_not_contains(self):
        assert validate_user_fragment("Привет мир", "земля") is False

    def test_multiple_spaces(self):
        assert validate_user_fragment("Привет   мир", "мир") is True

    def test_empty_fragment(self):
        assert validate_user_fragment("Привет мир", "") is True