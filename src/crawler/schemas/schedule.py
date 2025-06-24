from typing import Annotated

from pydantic import BaseModel, Field


class ScheduleParseMessageSchema(BaseModel):
    """Message schema for scheduled parsing tasks.

    Defines the structure of schedule messages from the message broker.
    """

    channel_id: Annotated[
        int,
        Field(..., description="ID of the community/user/chat"),
    ]
    last_message_id: Annotated[
        int,
        Field(
            ...,
            gt=0,
            description="Our last message ID in base",
        ),
    ]
