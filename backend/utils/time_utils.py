from datetime import datetime, timezone, timedelta

# Default user time-zone offset (can be moved to config)
USER_TZ_OFFSET = 3  # Moscow, Cyprus, Istanbul, etc.

def utc_to_user(dt_utc: datetime, tz_offset=USER_TZ_OFFSET):
    """
    Convert UTC datetime to the user's local time (e.g., +3 hours).
    """
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    return dt_utc + timedelta(hours=tz_offset)

def now_user(tz_offset=USER_TZ_OFFSET):
    """
    Get the current user-local datetime (e.g., +3 hours).
    """
    return datetime.utcnow().replace(tzinfo=timezone.utc) + timedelta(hours=tz_offset)

def format_user_datetime(dt: datetime, fmt="%Y-%m-%d %H:%M:%S", tz_offset=USER_TZ_OFFSET):
    """
    Format datetime as a string using the timezone offset.
    """
    dt_user = utc_to_user(dt, tz_offset)
    return dt_user.strftime(fmt)

# Example usage
# if __name__ == "__main__":
#     now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
#     print("UTC:", now_utc)
#     print("User local:", utc_to_user(now_utc))
#     print("User str:", format_user_datetime(now_utc))


def get_utc_now():
    return datetime.now(timezone.utc)


def to_user_tz_iso(dt: datetime | None, tz_offset=USER_TZ_OFFSET) -> str:
    """
    Serialize datetime in user timezone as ISO8601 with explicit offset.
    Naive datetime is treated as UTC source.
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    user_tz = timezone(timedelta(hours=tz_offset))
    return dt.astimezone(user_tz).isoformat(timespec="seconds")
