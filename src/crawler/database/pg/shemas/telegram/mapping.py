from sqlalchemy import BigInteger, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from crawler.database.pg.shemas.base import BaseSchema


class TelegramSessionEntityMap(BaseSchema):
    __tablename__ = "session_entity_map"
    entity_id: Mapped[int] = mapped_column(ForeignKey("crawler.entities.id"))
    session_id: Mapped[int] = mapped_column(ForeignKey("crawler.session.id"))

    __table_args__ = (
        UniqueConstraint("entity_id", "session_id", name="uix_entity_session"),
        {"schema": "crawler"},
    )
