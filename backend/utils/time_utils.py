from datetime import datetime, timezone, timedelta

# Основной часовой пояс пользователя (можно вынести в конфиг)
USER_TZ_OFFSET = 3  # Москва, Кипр, Стамбул и т.д.

def utc_to_user(dt_utc: datetime, tz_offset=USER_TZ_OFFSET):
    """
    Переводит datetime в локальное время пользователя (напр. +3 часа).
    """
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    return dt_utc + timedelta(hours=tz_offset)

def now_user(tz_offset=USER_TZ_OFFSET):
    """
    Получить текущее локальное время пользователя (напр. +3 часа)
    """
    return datetime.utcnow().replace(tzinfo=timezone.utc) + timedelta(hours=tz_offset)

def format_user_datetime(dt: datetime, fmt="%Y-%m-%d %H:%M:%S", tz_offset=USER_TZ_OFFSET):
    """
    Форматировать дату в строку с учётом сдвига пояса
    """
    dt_user = utc_to_user(dt, tz_offset)
    return dt_user.strftime(fmt)

# Пример использования
# if __name__ == "__main__":
#     now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
#     print("UTC:", now_utc)
#     print("User local:", utc_to_user(now_utc))
#     print("User str:", format_user_datetime(now_utc))


def get_utc_now():
    return datetime.now(timezone.utc)