from datetime import datetime

import pytz

MSK = pytz.timezone("Europe/Moscow")


def aware_now() -> datetime:
    return datetime.now(MSK)
