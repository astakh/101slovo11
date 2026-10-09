"""Тесты для app/utils/clustering.py — кластеризация слов."""
import pytest
from app.utils.clustering import cluster_words, _compute_group_sizes, _deterministic_shuffle


def _make_words(n: int) -> list[dict]:
    """Создаёт n тестовых слов."""
    return [
        {"word_id": i, "lemma": f"word{i}", "pos": "noun", "translations": [f"слово{i}"]}
        for i in range(n)
    ]


class TestComputeGroupSizes:
    """Тесты для _compute_group_sizes."""

    def test_zero_words(self):
        assert _compute_group_sizes(0) == []

    def test_one_word(self):
        assert _compute_group_sizes(1) == [1]

    def test_two_words(self):
        assert _compute_group_sizes(2) == [2]

    def test_three_words(self):
        assert _compute_group_sizes(3) == [3]

    def test_four_words(self):
        sizes = _compute_group_sizes(4)
        assert sum(sizes) == 4
        assert all(1 <= s <= 3 for s in sizes)
        assert len(sizes) == 2
        assert sizes == [2, 2]

    def test_five_words(self):
        sizes = _compute_group_sizes(5)
        assert sum(sizes) == 5
        assert all(1 <= s <= 3 for s in sizes)
        assert sizes == [2, 3]

    def test_six_words(self):
        sizes = _compute_group_sizes(6)
        assert sum(sizes) == 6
        assert sizes == [3, 3]

    def test_seven_words(self):
        sizes = _compute_group_sizes(7)
        assert sum(sizes) == 7
        assert sizes == [2, 2, 3]

    def test_ten_words(self):
        sizes = _compute_group_sizes(10)
        assert sum(sizes) == 10
        assert all(1 <= s <= 3 for s in sizes)
        # Разница между макс и мин <= 1
        assert max(sizes) - min(sizes) <= 1
        # Меньшие группы первыми
        assert sizes == sorted(sizes)

    def test_sizes_sorted_ascending(self):
        for n in range(1, 31):
            sizes = _compute_group_sizes(n)
            assert sizes == sorted(sizes), f"n={n}: sizes not sorted"

    def test_all_words_covered(self):
        for n in range(1, 31):
            sizes = _compute_group_sizes(n)
            assert sum(sizes) == n, f"n={n}: sum={sum(sizes)}"


class TestClusterWords:
    """Тесты для cluster_words."""

    def test_empty_words(self):
        result = cluster_words([], user_id=1, lesson_number=1)
        assert result == []

    def test_single_word(self):
        words = _make_words(1)
        groups = cluster_words(words, user_id=1, lesson_number=1)
        assert len(groups) == 1
        assert len(groups[0]) == 1
        assert groups[0][0]["word_id"] == 0

    def test_three_words_one_group(self):
        words = _make_words(3)
        groups = cluster_words(words, user_id=1, lesson_number=1)
        assert len(groups) == 1
        assert len(groups[0]) == 3

    def test_four_words_two_groups(self):
        words = _make_words(4)
        groups = cluster_words(words, user_id=1, lesson_number=1)
        assert len(groups) == 2
        total = sum(len(g) for g in groups)
        assert total == 4

    def test_ten_words_all_covered(self):
        words = _make_words(10)
        groups = cluster_words(words, user_id=1, lesson_number=1)
        all_ids = {w["word_id"] for g in groups for w in g}
        assert all_ids == {w["word_id"] for w in words}

    def test_group_sizes_max_3(self):
        words = _make_words(10)
        groups = cluster_words(words, user_id=1, lesson_number=1)
        for g in groups:
            assert len(g) <= 3

    def test_deterministic_same_seed(self):
        words = _make_words(10)
        g1 = cluster_words(words, user_id=1, lesson_number=5)
        g2 = cluster_words(words, user_id=1, lesson_number=5)
        assert g1 == g2

    def test_different_lesson_different_order(self):
        words = _make_words(10)
        g1 = cluster_words(words, user_id=1, lesson_number=1)
        g2 = cluster_words(words, user_id=1, lesson_number=2)
        # Порядок может совпасть случайно, но для 10 слов — крайне маловероятно
        flat1 = [w["word_id"] for g in g1 for w in g]
        flat2 = [w["word_id"] for g in g2 for w in g]
        assert flat1 != flat2

    def test_different_user_different_order(self):
        words = _make_words(10)
        g1 = cluster_words(words, user_id=1, lesson_number=1)
        g2 = cluster_words(words, user_id=2, lesson_number=1)
        flat1 = [w["word_id"] for g in g1 for w in g]
        flat2 = [w["word_id"] for g in g2 for w in g]
        assert flat1 != flat2

    def test_no_duplicates_in_groups(self):
        words = _make_words(15)
        groups = cluster_words(words, user_id=42, lesson_number=7)
        all_ids = [w["word_id"] for g in groups for w in g]
        assert len(all_ids) == len(set(all_ids))


class TestDeterministicShuffle:
    """Тесты для _deterministic_shuffle."""

    def test_same_seed_same_result(self):
        items = list(range(20))
        s1 = _deterministic_shuffle(items, "seed1")
        s2 = _deterministic_shuffle(items, "seed1")
        assert s1 == s2

    def test_different_seed_different_result(self):
        items = list(range(20))
        s1 = _deterministic_shuffle(items, "seed1")
        s2 = _deterministic_shuffle(items, "seed2")
        assert s1 != s2

    def test_does_not_modify_original(self):
        items = list(range(10))
        original = items.copy()
        _deterministic_shuffle(items, "seed")
        assert items == original

    def test_all_elements_present(self):
        items = list(range(10))
        shuffled = _deterministic_shuffle(items, "seed")
        assert sorted(shuffled) == sorted(items)