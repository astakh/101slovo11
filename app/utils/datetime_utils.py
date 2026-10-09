from datetime import datetime, date, time, timezone, timedelta
from zoneinfo import ZoneInfo

# Фиксированный часовой пояс приложения
APP_TIMEZONE = ZoneInfo("Europe/Moscow")


def get_user_tz(timezone_str: str | None = None) -> ZoneInfo:
    """Возвращает часовой пояс приложения (всегда Europe/Moscow)."""
    return APP_TIMEZONE


def get_user_today(timezone_str: str | None = None) -> date:
    """Возвращает текущую дату по московскому времени."""
    return datetime.now(APP_TIMEZONE).date()


def get_resets_at(timezone_str: str | None = None) -> datetime:
    """Возвращает время сброса дневного лимита (00:00 по Москве, в UTC)."""
    now = datetime.now(APP_TIMEZONE)
    tomorrow = now.date() + timedelta(days=1)
    reset_time = datetime.combine(tomorrow, time(0, 0, 0), tzinfo=APP_TIMEZONE)
    return reset_time.astimezone(timezone.utc)