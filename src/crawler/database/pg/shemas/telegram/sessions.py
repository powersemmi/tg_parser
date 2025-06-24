from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped

from crawler.database.pg.shemas.base import BaseSchema


class TelegramSession(BaseSchema):
    __tablename__ = "session"
    __table_args__ = ({"schema": "crawler"},)
    session: Mapped[str]
    api_id: Mapped[str]
    api_hash: Mapped[str]
    tel: Mapped[str]
    proxy: Mapped[str]

    @classmethod
    async def get_all_id(cls, session: AsyncSession) -> list[int]:
        stmt = select(cls.id)
        result = await session.execute(stmt)
        return cast(list[int], result.scalars().all())
