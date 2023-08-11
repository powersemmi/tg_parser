from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped

from .base import BaseSchema


class Message(BaseSchema):
    __tablename__ = "messages"
    message_raw: Mapped[JSONB]
