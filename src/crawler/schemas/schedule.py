from typing import Annotated

from pydantic import BaseModel, Field


class ScheduleParseMessageSchema(BaseModel):
    channel_id: Annotated[
        int,
        Field(..., description="id сообщества/пользователя/чат"),
    ]
    from_message_id: Annotated[
        int,
        Field(
            ...,
            gt=0,
            description="С какого id сообщения собирать",
        ),
    ]
