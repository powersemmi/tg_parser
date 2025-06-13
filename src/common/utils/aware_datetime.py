from datetime import datetime
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")


def aware_now() -> datetime:
    return datetime.now(MSK)
