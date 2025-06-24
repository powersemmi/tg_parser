from typing import cast

from sqlalchemy import BigInteger, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from crawler.database.pg.shemas.base import BaseSchema


class TelegramEntity(BaseSchema):
    __tablename__ = "entities"
    __table_args__ = ({"schema": "crawler"},)
    entity_id: Mapped[int] = mapped_column(BigInteger)
    entity_name: Mapped[str]
    entity_url: Mapped[str]

    @classmethod
    async def get_all_id(cls, session: AsyncSession) -> list[int]:
        stmt = select(cls.id)
        result = await session.execute(stmt)
        return cast(list[int], result.scalars().all())
