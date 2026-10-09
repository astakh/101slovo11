"""Тесты для app/utils/datetime_utils.py — работа с таймзонами."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import pytest
from app.utils.datetime_utils import get_user_tz, get_user_today, get_resets_at


class TestGetUserTz:
    def test_none_returns_utc(self):
        tz = get_user_tz(None)
        assert tz == ZoneInfo("UTC")

    def test_empty_string_returns_utc(self):
        tz = get_user_tz("")
        assert tz == ZoneInfo("UTC")

    def test_valid_timezone(self):
        tz = get_user_tz("Europe/Moscow")
        assert tz == ZoneInfo("Europe/Moscow")

    def test_invalid_timezone_returns_utc(self):
        tz = get_user_tz("Invalid/Timezone")
        assert tz == ZoneInfo("UTC")


class TestGetUserToday:
    def test_none_timezone(self):
        today = get_user_today(None)
        assert isinstance(today, date)
        assert today == datetime.now(ZoneInfo("UTC")).date()

    def test_returns_date(self):
        today = get_user_today("Europe/Moscow")
        assert isinstance(today, date)


class TestGetResetsAt:
    def test_returns_datetime_utc(self):
        resets_at = get_resets_at("Europe/Moscow")
        assert resets_at.tzinfo == timezone.utc

    def test_resets_at_is_tomorrow(self):
        tz = ZoneInfo("Europe/Moscow")
        now_msk = datetime.now(tz)
        resets_at = get_resets_at("Europe/Moscow")
        # resets_at должен быть завтра по МСК
        tomorrow_msk = (now_msk + timedelta(days=1)).date()
        resets_at_msk = resets_at.astimezone(tz)
        assert resets_at_msk.date() == tomorrow_msk
        assert resets_at_msk.hour == 0
        assert resets_at_msk.minute == 0

    def test_none_timezone(self):
        resets_at = get_resets_at(None)
        assert resets_at.tzinfo == timezone.utc