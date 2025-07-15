from typing import cast

from sqlalchemy import BigInteger, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from crawler.database.pg.schemas.base import BaseSchema


class TelegramSession(BaseSchema):
    """Модель сессии Telegram для доступа к API.

    Хранит данные авторизации и настройки для подключения к Telegram API.
    Каждая сессия представляет отдельный аккаунт Telegram, который может
    использоваться для сбора данных из различных каналов.

    Атрибуты:
        session: Строка сессии Telegram в формате StringSession
        api_id: ID приложения Telegram API
        api_hash: Хеш приложения Telegram API
        tel: Номер телефона, связанный с аккаунтом
        proxy: Настройки прокси (URL) для подключения
    """

    __tablename__ = "sessions"
    __table_args__ = ({"schema": "crawler"},)
    session: Mapped[str]
    api_id: Mapped[int] = mapped_column(BigInteger)
    api_hash: Mapped[str]
    tel: Mapped[str]
    proxy: Mapped[str]

    @classmethod
    async def get_all_id(cls, session: AsyncSession) -> list[int]:
        stmt = select(cls.id)
        result = await session.execute(stmt)
        return cast(list[int], result.scalars().all())
