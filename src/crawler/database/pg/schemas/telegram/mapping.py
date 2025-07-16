from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from crawler.database.pg.schemas.base import BaseSchema


class TelegramSessionEntityMap(BaseSchema):
    """Модель связи между сессиями Telegram и сущностями.

    Таблица отношений many-to-many, связывающая сессии Telegram
    с сущностями (каналами, чатами, пользователями). Используется для
    отслеживания, какие сессии уже подписаны на какие каналы.

    Атрибуты:
        entity_id: ID сущности Telegram (внешний ключ)
        session_id: ID сессии Telegram (внешний ключ)
    """

    __tablename__ = "session_entity_map"
    entity_id: Mapped[int] = mapped_column(ForeignKey("crawler.entities.id"))
    session_id: Mapped[int] = mapped_column(ForeignKey("crawler.session.id"))

    __table_args__ = (
        UniqueConstraint("entity_id", "session_id", name="uix_entity_session"),
        {"schema": "crawler"},
    )
