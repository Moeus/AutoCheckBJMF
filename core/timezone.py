from datetime import datetime, timedelta, timezone


# 固定东八区，不依赖操作系统时区或额外的时区数据库。
BEIJING_TZ = timezone(timedelta(hours=8), "UTC+8")
TIMEZONE_LABEL = "北京时间（UTC+8）"


def beijing_now() -> datetime:
    return datetime.now(BEIJING_TZ)


def as_beijing(value: datetime) -> datetime:
    """带时区时间转为东八区；无时区的调度时间按北京时间解释。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=BEIJING_TZ)
    return value.astimezone(BEIJING_TZ)
