"""Тесты для app/utils/streak.py — расчёт стрика."""
from datetime import date, timedelta
import pytest
from app.utils.streak import calculate_streak


TODAY = date(2026, 10, 9)


class TestCalculateStreakEmpty:
    def test_empty_dates(self):
        result = calculate_streak([], TODAY)
        assert result == {"current": 0, "longest": 0, "today_done": False}


class TestCalculateStreakSingle:
    def test_single_today(self):
        result = calculate_streak([TODAY], TODAY)
        assert result["current"] == 1
        assert result["longest"] == 1
        assert result["today_done"] is True

    def test_single_yesterday(self):
        yesterday = TODAY - timedelta(days=1)
        result = calculate_streak([yesterday], TODAY)
        assert result["current"] == 1
        assert result["longest"] == 1
        assert result["today_done"] is False

    def test_single_two_days_ago(self):
        two_days_ago = TODAY - timedelta(days=2)
        result = calculate_streak([two_days_ago], TODAY)
        assert result["current"] == 0
        assert result["longest"] == 1
        assert result["today_done"] is False


class TestCalculateStreakConsecutive:
    def test_three_consecutive(self):
        dates = [
            TODAY - timedelta(days=2),
            TODAY - timedelta(days=1),
            TODAY,
        ]
        result = calculate_streak(dates, TODAY)
        assert result["current"] == 3
        assert result["longest"] == 3
        assert result["today_done"] is True

    def test_five_consecutive(self):
        dates = [TODAY - timedelta(days=i) for i in range(5)]
        result = calculate_streak(dates, TODAY)
        assert result["current"] == 5
        assert result["longest"] == 5


class TestCalculateStreakGap:
    def test_gap_breaks_streak(self):
        dates = [
            TODAY - timedelta(days=5),
            TODAY - timedelta(days=4),
            TODAY - timedelta(days=3),
            # пропуск 2 дней
            TODAY - timedelta(days=1),
            TODAY,
        ]
        result = calculate_streak(dates, TODAY)
        assert result["current"] == 2
        assert result["longest"] == 3

    def test_gap_two_days_ago_breaks(self):
        dates = [TODAY - timedelta(days=2)]
        result = calculate_streak(dates, TODAY)
        assert result["current"] == 0

    def test_yesterday_not_broken(self):
        dates = [TODAY - timedelta(days=1)]
        result = calculate_streak(dates, TODAY)
        assert result["current"] == 1


class TestCalculateStreakFuture:
    def test_future_dates_capped(self):
        future = TODAY + timedelta(days=3)
        result = calculate_streak([future], TODAY)
        # Будущая дата → today
        assert result["today_done"] is True
        assert result["current"] == 1

    def test_mixed_future_and_past(self):
        dates = [
            TODAY - timedelta(days=1),
            TODAY,
            TODAY + timedelta(days=2),  # → capped to today
        ]
        result = calculate_streak(dates, TODAY)
        assert result["current"] == 2
        assert result["longest"] == 2


class TestCalculateStreakDuplicates:
    def test_duplicate_dates(self):
        dates = [TODAY, TODAY, TODAY]
        result = calculate_streak(dates, TODAY)
        assert result["current"] == 1
        assert result["longest"] == 1

    def test_duplicates_in_consecutive(self):
        dates = [
            TODAY - timedelta(days=1),
            TODAY - timedelta(days=1),
            TODAY,
            TODAY,
        ]
        result = calculate_streak(dates, TODAY)
        assert result["current"] == 2
        assert result["longest"] == 2


class TestCalculateStreakLongest:
    def test_longest_not_current(self):
        """Длинный стрик в прошлом, текущий — короткий."""
        dates = [
            TODAY - timedelta(days=10),
            TODAY - timedelta(days=9),
            TODAY - timedelta(days=8),
            TODAY - timedelta(days=7),
            # пропуск
            TODAY - timedelta(days=1),
            TODAY,
        ]
        result = calculate_streak(dates, TODAY)
        assert result["longest"] == 4
        assert result["current"] == 2

    def test_unsorted_input(self):
        """Даты не отсортированы — функция должна справиться."""
        dates = [TODAY, TODAY - timedelta(days=2), TODAY - timedelta(days=1)]
        result = calculate_streak(dates, TODAY)
        assert result["current"] == 3
        assert result["longest"] == 3