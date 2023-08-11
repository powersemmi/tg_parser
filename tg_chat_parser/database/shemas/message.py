from typing import Any

from sqlalchemy.orm import Mapped

from .base import BaseSchema


class Message(BaseSchema):
    __tablename__ = "messages"
    message_raw: Mapped[dict[str, Any]]
