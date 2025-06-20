from .base import BaseSchema


class Session(BaseSchema):
    __tablename__ = "session"
    __table_args__ = {"schema": "telegram"}
