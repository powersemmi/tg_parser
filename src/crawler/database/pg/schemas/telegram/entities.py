import logging
from typing import Self

from sqlalchemy import BigInteger, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from crawler.database.pg.schemas.base import BaseSchema

logger = logging.getLogger(__name__)


class Entities(BaseSchema):
    """Модель сущности Telegram (канала, чата, пользователя).

    Хранит основную информацию о сущностях Telegram, которые используются
    в системе сбора данных. Для каждой сущности сохраняется:
    - entity_id: ID сущности в Telegram
    - entity_name: Имя сущности (название канала, имя пользователя)
    - entity_url: URL сущности для доступа в Telegram
    """

    __table_args__ = ({"schema": "crawler"},)
    entity_id: Mapped[int] = mapped_column(BigInteger)
    entity_name: Mapped[str]
    entity_url: Mapped[str]

    @classmethod
    async def get_by_url(
        cls, session: AsyncSession, channel_url: str
    ) -> Self | None:
        """
        Найти сущность канала в базе данных по URL.

        Args:
            session: Сессия SQLAlchemy
            channel_url: URL канала

        Returns:
            Объект Entities или None, если не найден
        """
        stmt = select(cls).where(cls.entity_url == channel_url)
        result = await session.execute(stmt)
        return result.scalars().first()

    @classmethod
    async def create_entity(
        cls,
        session: AsyncSession,
        channel_url: str,
        entity_id: int,
        entity_name: str,
    ) -> tuple[Self, bool]:
        """
        Получить или создать сущность канала в базе данных.

        Args:
            session: Сессия SQLAlchemy
            channel_url: URL канала
            entity_id: ID сущности
            entity_name: Имя сущности

        Returns:
            Кортеж (entity, is_new), где:
            - entity: объект Entities
            - is_new: флаг, показывающий, была ли создана новая сущность
        """
        # Сначала пробуем найти существующую сущность по URL
        existing_entity = await cls.get_by_url(session, channel_url)

        if existing_entity is not None:
            return existing_entity, False

        # Если не найдено по URL, проверяем по entity_id
        existing_entity = await cls.get_by_entity_id(session, entity_id)

        if existing_entity is not None:
            return existing_entity, False

        # Создаем новую сущность, если не найдена
        new_entity = await super()._create(
            session=session,
            entity_id=entity_id,
            entity_name=entity_name,
            entity_url=channel_url,
        )

        return new_entity, True

    @classmethod
    async def get_by_entity_id(
        cls, session: AsyncSession, entity_id: int
    ) -> Self | None:
        """
        Найти сущность канала в базе данных по entity_id.

        Args:
            session: Сессия SQLAlchemy
            entity_id: ID сущности (entity_id, не первичный ключ id)

        Returns:
            Объект Entities или None, если не найден
        """
        stmt = select(cls).where(cls.entity_id == entity_id)
        result = await session.execute(stmt)
        return result.scalars().first()
