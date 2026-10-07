from datetime import datetime, date, time, timezone, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

def get_user_tz(timezone_str: str | None) -> ZoneInfo:
    if not timezone_str:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(timezone_str)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")

def get_user_today(timezone_str: str | None) -> date:
    tz = get_user_tz(timezone_str)
    return datetime.now(tz).date()

def get_resets_at(timezone_str: str | None) -> datetime:
    tz = get_user_tz(timezone_str)
    now = datetime.now(tz)
    tomorrow = now.date() + timedelta(days=1)
    reset_time = datetime.combine(tomorrow, time(0, 0, 0), tzinfo=tz)
    return reset_time.astimezone(timezone.utc)