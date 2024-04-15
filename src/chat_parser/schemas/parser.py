from typing import Annotated

from pydantic import AwareDatetime, BaseModel, Field, HttpUrl


class ParseMessage(BaseModel):
    channel_url: Annotated[
        HttpUrl,
        Field(..., description="Ссылка на сообщество/пользователя/чат"),
    ]
    massage_limit: Annotated[
        int, Field(..., gt=0, description="Сколько сообщений собрать")
    ]
    date_offset: Annotated[
        AwareDatetime | None,
        Field(None, description="С какой datetime собирать"),
    ]
    offset_msg_id: Annotated[
        int | None,
        Field(
            None,
            gt=0,
            description="С какого id сообщения собирать",
        ),
    ]
