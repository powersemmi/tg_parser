from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from crawler.database.pg.schemas.base import BaseSchema

from .entities import Entities
from .sessions import Sessions


class SessionEntityMap(BaseSchema):
    """Модель связи между сессиями Telegram и сущностями.

    Таблица отношений many-to-many, связывающая сессии Telegram
    с сущностями (каналами, чатами, пользователями). Используется для
    отслеживания, какие сессии уже подписаны на какие каналы.

    Атрибуты:
        entity_id: ID сущности Telegram (внешний ключ)
        session_id: ID сессии Telegram (внешний ключ)
    """

    entity_id: Mapped[int] = mapped_column(
        ForeignKey(Entities.id, ondelete="CASCADE")
    )
    session_id: Mapped[int] = mapped_column(
        ForeignKey(Sessions.id, ondelete="CASCADE")
    )

    __table_args__ = (
        UniqueConstraint(entity_id, session_id, name="uix_entity_session"),
        {"schema": "crawler"},
    )
