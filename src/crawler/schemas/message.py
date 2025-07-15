"""Schema for message response models.

Contains models for representing collected messages.
"""

from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, Field


class MessageResponseModel(BaseModel):
    """Message response model for ClickHouse.

    Defines the structure of messages sent to ClickHouse.
    Основано на полях из telethon.tl.types.Message:
    - id -> message_id: ID сообщения
    - date: дата отправки
    - message/text -> message: текст сообщения
    - from_id -> sender_id: отправитель
    - peer_id -> entity_id: ID чата/канала
    - reply_to -> reply_to_message_id: информация о сообщении,
    на которое отвечают
    - reactions: реакции на сообщение
    """

    message_id: Annotated[
        int, Field(..., description="Unique ID of the message")
    ]
    entity_id: Annotated[
        int,
        Field(
            ..., description="ID of the Telegram entity (channel/chat/user)"
        ),
    ]
    entity_name: Annotated[
        str, Field(..., description="Name of the Telegram entity")
    ]
    sender_id: Annotated[
        int | None,
        Field(None, description="ID of the message sender if available"),
    ]
    sender_name: Annotated[
        str | None,
        Field(None, description="Name of the message sender if available"),
    ]
    date: Annotated[
        datetime,
        Field(..., description="Date and time when the message was sent"),
    ]
    message: Annotated[
        str,
        Field(
            "",
            description="Text content of the message "
            "(from message or text field)",
        ),
    ]
    reactions: Annotated[
        list[dict[str, Any]],
        Field(
            default_factory=list,
            description="List of reactions to the message with "
            "emoji and count",
        ),
    ]
    views: Annotated[
        int | None,
        Field(None, description="Number of views for the message"),
    ]
    forwards: Annotated[
        int | None,
        Field(None, description="Number of forwards for the message"),
    ]
    replies: Annotated[
        int | None,
        Field(None, description="Number of replies to the message"),
    ]
    media_type: Annotated[
        str | None,
        Field(None, description="Type of media attached to the message"),
    ]
    media_url: Annotated[
        str | None, Field(None, description="URL of media if available")
    ]
    reply_to_message_id: Annotated[
        int | None,
        Field(None, description="ID of the message this is a reply to"),
    ]
    metadata: Annotated[
        dict[str, Any],
        Field(
            default_factory=dict,
            description="Additional metadata like entities, etc.",
        ),
    ]
