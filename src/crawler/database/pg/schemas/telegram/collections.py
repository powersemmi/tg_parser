from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import and_, or_

from crawler.database.pg.schemas.base import BaseSchema
from crawler.database.pg.schemas.telegram.entities import TelegramEntity


class TelegramChannelCollection(BaseSchema):
    """
    Хранит метаданные о сборе данных из каналов.
    Записывает диапазон собранных сообщений (по id и datetime).
    """

    __tablename__ = "channel_collections"
    __table_args__ = (
        UniqueConstraint(
            "entity_id",
            "from_message_id",
            "to_message_id",
            name="uix_entity_message_range",
        ),
        Index(
            "ix_entity_datetime_range",
            "entity_id",
            "from_datetime",
            "to_datetime",
        ),
        {"schema": "crawler"},
    )

    entity_id: Mapped[int] = mapped_column(ForeignKey("crawler.entities.id"))
    entity: Mapped[TelegramEntity] = relationship(
        "TelegramEntity", lazy="joined"
    )

    # Диапазон сообщений по ID
    from_message_id: Mapped[int] = mapped_column(BigInteger)
    to_message_id: Mapped[int] = mapped_column(BigInteger)

    # Диапазон сообщений по дате
    from_datetime: Mapped[datetime]
    to_datetime: Mapped[datetime]

    # Количество собранных сообщений
    messages_count: Mapped[int] = mapped_column(Integer, default=0)

    @classmethod
    async def check_overlap(
        cls,
        session: AsyncSession,
        entity_id: int,
        from_datetime: datetime,
        to_datetime: datetime | None,
    ) -> tuple[bool, list["TelegramChannelCollection"]]:
        """
        Checks if the specified time range overlaps with
        already collected data.

        Args:
            session: SQLAlchemy session
            entity_id: Channel entity ID
            from_datetime: Start date of the requested range
            to_datetime: End date of the requested range
                (if None, from_datetime is used)

        Returns:
            Tuple (has_overlap, overlapping_collections):
            - has_overlap: True if there is an overlap (data already collected)
            - overlapping_collections: List of overlapping collections
        """
        if to_datetime is None:
            to_datetime = from_datetime

        # Find records with time overlap for the specified channel
        stmt = (
            select(cls)
            .where(
                and_(
                    cls.entity_id == entity_id,
                    or_(
                        # Any range intersection:
                        # 1. Start of new range falls within existing one
                        and_(
                            cls.from_datetime <= from_datetime,
                            from_datetime <= cls.to_datetime,
                        ),
                        # 2. End of new range falls within existing one
                        and_(
                            cls.from_datetime <= to_datetime,
                            to_datetime <= cls.to_datetime,
                        ),
                        # 3. New range completely covers existing one
                        and_(
                            from_datetime <= cls.from_datetime,
                            cls.to_datetime <= to_datetime,
                        ),
                    ),
                )
            )
            .order_by(cls.from_datetime)
        )

        result = await session.execute(stmt)
        overlapping_collections = list(result.scalars().all())
        return bool(overlapping_collections), overlapping_collections

    @classmethod
    async def find_non_overlapping_ranges(
        cls,
        session: AsyncSession,
        entity_id: int,
        from_datetime: datetime,
        to_datetime: datetime | None = None,
    ) -> list[tuple[datetime, datetime]]:
        """
        Находит непересекающиеся диапазоны дат, которые нужно собрать.

        Args:
            session: Сессия SQLAlchemy
            entity_id: ID сущности канала
            from_datetime: Начальная дата запрашиваемого диапазона
            to_datetime: Конечная дата запрашиваемого диапазона
                (если None, используется текущая дата)

        Returns:
            Список кортежей (from_dt, to_dt) с диапазонами,
            которые нужно собрать
        """
        if to_datetime is None:
            to_datetime = datetime.now(from_datetime.tzinfo)

        # Получаем все перекрывающиеся коллекции
        has_overlap, overlapping = await cls.check_overlap(
            session=session,
            entity_id=entity_id,
            from_datetime=from_datetime,
            to_datetime=to_datetime,
        )

        if not has_overlap:
            # Если нет пересечений, возвращаем весь запрошенный диапазон
            return [(from_datetime, to_datetime)]

        # Сортируем коллекции по времени начала
        sorted_collections = sorted(overlapping, key=lambda x: x.from_datetime)

        # Находим непересекающиеся диапазоны
        ranges_to_collect = []
        current_time = from_datetime

        for collection in sorted_collections:
            # Если есть промежуток между текущим временем и началом коллекции
            if current_time < collection.from_datetime:
                ranges_to_collect.append((
                    current_time,
                    collection.from_datetime,
                ))

            # Обновляем текущее время до конца коллекции, если оно больше
            if collection.to_datetime > current_time:
                current_time = collection.to_datetime

        # Проверяем, есть ли диапазон после последней коллекции
        if current_time < to_datetime:
            ranges_to_collect.append((current_time, to_datetime))

        return ranges_to_collect

    @classmethod
    async def create_collection_record(
        cls,
        session: AsyncSession,
        entity_id: int,
        from_message_id: int,
        to_message_id: int,
        from_datetime: datetime,
        to_datetime: datetime,
        messages_count: int,
    ) -> "TelegramChannelCollection":
        """
        Создает новую запись о собранных данных из канала.
        """
        collection = cls(
            entity_id=entity_id,
            from_message_id=from_message_id,
            to_message_id=to_message_id,
            from_datetime=from_datetime,
            to_datetime=to_datetime,
            messages_count=messages_count,
        )
        session.add(collection)
        await session.flush()
        return collection

    @classmethod
    async def get_channel_collections(
        cls, session: AsyncSession, entity_id: int, from_datetime: datetime
    ) -> list["TelegramChannelCollection"]:
        """
        Получает все записи о сборах данных для указанного канала.
        """
        stmt = (
            select(cls)
            .where(
                cls.entity_id == entity_id,
                cls.from_datetime >= from_datetime,
            )
            .order_by(cls.from_datetime)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())
