"""Тесты для app/utils/srs.py — чистая функция SRS."""
import pytest
from app.utils.srs import srs_update, INTERVALS, MAX_STAGE


class TestSrsUpdateCorrect:
    """result = 'correct'"""

    def test_stage0_to_stage1(self):
        stage, due, status = srs_update(0, "correct", lesson_number=1)
        assert stage == 1
        assert due == 1 + INTERVALS[0]  # 1 + 1 = 2
        assert status == "active"

    def test_stage1_to_stage2(self):
        stage, due, status = srs_update(1, "correct", lesson_number=5)
        assert stage == 2
        assert due == 5 + INTERVALS[1]  # 5 + 2 = 7
        assert status == "active"

    def test_stage2_to_stage3(self):
        stage, due, status = srs_update(2, "correct", lesson_number=10)
        assert stage == 3
        assert due == 10 + INTERVALS[2]  # 10 + 3 = 13
        assert status == "active"

    def test_stage3_to_stage4(self):
        stage, due, status = srs_update(3, "correct", lesson_number=7)
        assert stage == 4
        assert due == 7 + INTERVALS[3]  # 7 + 7 = 14
        assert status == "active"

    def test_stage4_to_stage5(self):
        stage, due, status = srs_update(4, "correct", lesson_number=3)
        assert stage == 5
        assert due == 3 + INTERVALS[4]  # 3 + 11 = 14
        assert status == "active"

    def test_stage5_to_stage6(self):
        stage, due, status = srs_update(5, "correct", lesson_number=1)
        assert stage == 6
        assert due == 1 + INTERVALS[5]  # 1 + 30 = 31
        assert status == "active"

    def test_stage6_mastered(self):
        """На максимальной стадии → mastered, due=None."""
        stage, due, status = srs_update(MAX_STAGE, "correct", lesson_number=10)
        assert stage == MAX_STAGE
        assert due is None
        assert status == "mastered"


class TestSrsUpdateTypo:
    """result = 'typo' — ведёт себя как correct для SRS."""

    def test_typo_same_as_correct(self):
        for stage in range(MAX_STAGE + 1):
            r_correct = srs_update(stage, "correct", lesson_number=5)
            r_typo = srs_update(stage, "typo", lesson_number=5)
            assert r_correct == r_typo, f"Mismatch at stage {stage}"


class TestSrsUpdateIncorrect:
    """result = 'incorrect'"""

    def test_stage0_stays_0(self):
        stage, due, status = srs_update(0, "incorrect", lesson_number=1)
        assert stage == 0
        assert due == 1 + INTERVALS[0]  # 1 + 1 = 2
        assert status == "active"

    def test_stage1_drops_to_0(self):
        stage, due, status = srs_update(1, "incorrect", lesson_number=1)
        assert stage == 0
        assert due == 1 + INTERVALS[0]
        assert status == "active"

    def test_stage3_drops_to_2(self):
        stage, due, status = srs_update(3, "incorrect", lesson_number=10)
        assert stage == 2
        assert due == 10 + INTERVALS[1]  # 10 + 2 = 12
        assert status == "active"

    def test_stage5_drops_to_4(self):
        stage, due, status = srs_update(5, "incorrect", lesson_number=1)
        assert stage == 4
        assert due == 1 + INTERVALS[3]  # 1 + 7 = 8
        assert status == "active"

    def test_mastered_drops_to_stage5(self):
        """mastered (stage 6) + incorrect → stage 5, active."""
        stage, due, status = srs_update(MAX_STAGE, "incorrect", lesson_number=1)
        assert stage == MAX_STAGE - 1  # 5
        assert due == 1 + INTERVALS[4]  # 1 + 11 = 12
        assert status == "active"


class TestSrsIntervals:
    """Проверка самих интервалов."""

    def test_intervals_values(self):
        assert INTERVALS == [1, 2, 3, 7, 11, 30]

    def test_intervals_length(self):
        assert len(INTERVALS) == MAX_STAGE  # 6 интервалов для стадий 1–6

    def test_intervals_monotonic(self):
        for i in range(1, len(INTERVALS)):
            assert INTERVALS[i] > INTERVALS[i - 1]


class TestSrsEdgeCases:
    """Граничные случаи."""

    def test_unknown_result_treated_as_incorrect(self):
        """Неизвестный результат → не в ('correct','typo') → incorrect."""
        stage, due, status = srs_update(3, "unknown", lesson_number=1)
        assert stage == 2  # как incorrect
        assert status == "active"

    def test_empty_result_treated_as_incorrect(self):
        stage, due, status = srs_update(2, "", lesson_number=1)
        assert stage == 1  # как incorrect

    def test_large_lesson_number(self):
        stage, due, status = srs_update(0, "correct", lesson_number=10000)
        assert stage == 1
        assert due == 10001

    def test_due_always_positive(self):
        for stage in range(MAX_STAGE + 1):
            for result in ("correct", "typo", "incorrect"):
                _, due, _ = srs_update(stage, result, lesson_number=1)
                if due is not None:
                    assert due > 0, f"due={due} for stage={stage}, result={result}"