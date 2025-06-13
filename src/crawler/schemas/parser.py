from datetime import datetime, timedelta
from typing import Annotated

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    Field,
    HttpUrl,
)


# Функция-валидатор
def not_older_than_30_days(dt: AwareDatetime) -> AwareDatetime:
    if dt < datetime.now(dt.tzinfo) - timedelta(days=30):
        raise ValueError(
            "Дата не должна быть старше 30 дней от текущего времени"
        )
    return dt


# Используем Annotated и AfterValidator
RecentDateTime = Annotated[
    AwareDatetime, AfterValidator(not_older_than_30_days)
]


class ScheduleParseMessageSchema(BaseModel):
    channel_id: Annotated[
        int,
        Field(..., description="id сообщества/пользователя/чат"),
    ]
    from_message_id: Annotated[
        int,
        Field(
            None,
            gt=0,
            description="С какого id сообщения собирать",
        ),
    ]


class NewChannelParseMessageBody(BaseModel):
    channel_url: Annotated[
        HttpUrl,
        Field(..., description="Ссылка на сообщество/пользователя/чат"),
    ]
    datetime_offset: Annotated[
        RecentDateTime,
        Field(None, description="С какой datetime собирать"),
    ]
