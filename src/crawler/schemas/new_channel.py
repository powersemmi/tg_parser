from datetime import datetime, timedelta
from typing import Annotated

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    Field,
    HttpUrl,
)


def not_older_than_30_days(dt: AwareDatetime) -> AwareDatetime:
    """Validate that the datetime is not older than 30 days.

    Args:
        dt: Datetime to validate

    Returns:
        The validated datetime

    Raises:
        ValueError: If datetime is older than 30 days
    """
    if dt < datetime.now(dt.tzinfo) - timedelta(days=30):
        raise ValueError(
            "Date must not be older than 30 days from current time"
        )
    return dt


type RecentDateTime = Annotated[
    AwareDatetime, AfterValidator(not_older_than_30_days)
]


class NewChannelParseMessageBody(BaseModel):
    """Message schema for new channel parsing requests.

    Defines the structure of new channel messages from the message broker.
    """

    channel_url: Annotated[
        HttpUrl,
        Field(..., description="URL to the community/user/chat"),
    ]
    datetime_offset: Annotated[
        RecentDateTime,
        Field(..., description="Datetime to start collecting from"),
    ]
