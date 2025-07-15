import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import NamedTuple

from faststream.nats import NatsMessage
from nats.js.errors import KeyValueError
from sqlalchemy.ext.asyncio import AsyncSession
from telethon.hints import Entity
from telethon.tl.types import Channel, Chat, User

from common.utils.nats.resource_manager import ResourceLockManager
from crawler.database.pg.queries.session_entity import (
    find_subscribed_session,
)
from crawler.database.pg.schemas import TelegramEntity, TelegramSession
from crawler.database.pg.schemas.telegram.collections import (
    TelegramChannelCollection,
)
from crawler.database.tg import ConnectManager
from crawler.procedures.parser import TelegramMessageMetadata, collect_messages
from crawler.schemas.message import MessageResponseModel

logger = logging.getLogger(__name__)


class SessionResult(NamedTuple):
    """Result of session preparation."""

    db_entity: TelegramEntity | None
    connect_manager: ConnectManager
    db_session: TelegramSession | None
    tg_entity: Entity


async def _prepare_new_channel_session(
    session: AsyncSession,
    rlm: ResourceLockManager,
    channel_url: str,
) -> SessionResult:
    """
    Prepare session for new channels or channel without a subscribed session.
    """
    # Получаем сессию из общего пула
    db_session_id = await rlm.session().__aenter__()
    db_session = await TelegramSession.get(session=session, id=db_session_id)
    if db_session is None:
        await rlm.update_resources(
            await TelegramSession.get_all_id(session=session)
        )
        logger.warning(
            "Session %s not found, update local sessions",
            db_session_id,
        )
        raise ValueError(f"Session {db_session_id} not found")

    # Создаем ConnectManager
    connect_manager = ConnectManager(
        session=db_session.session,
        api_id=db_session.api_id,
        api_hash=db_session.api_hash,
        proxy=db_session.proxy,
    )
    await connect_manager.open()

    async with connect_manager.get_client() as client:
        # Получаем информацию о канале из Telegram
        tg_entity = await client.get_entity(channel_url)

    # В зависимости от типа сущности, получаем ID и имя
    if isinstance(tg_entity, Channel | Chat):
        entity_id = tg_entity.id
        entity_name = tg_entity.title
    elif isinstance(tg_entity, User):
        entity_id = tg_entity.id
        entity_name = tg_entity.username
    else:
        raise ValueError(f"Неизвестный тип сущности: {type(tg_entity)}")

    db_entity = await TelegramEntity.create_entity(
        session=session,
        channel_url=channel_url,
        entity_id=entity_id,
        entity_name=entity_name,
    )
    await session.commit()

    return SessionResult(db_entity, connect_manager, db_session, tg_entity)


async def _prepare_subscribed_session(
    db_entity: TelegramEntity,
    db_session: TelegramSession,
    rlm: ResourceLockManager,
) -> SessionResult:
    """Prepare session for channels with existing subscribed session."""
    # Используем подписанную сессию
    if db_session and await rlm.lock(db_session.id):
        logger.info(
            "Successfully acquired session %s "
            "already subscribed to channel %s",
            db_session.id,
            db_entity.entity_url,
        )

        connect_manager = ConnectManager(
            session=db_session.session,
            api_id=db_session.api_id,
            api_hash=db_session.api_hash,
            proxy=db_session.proxy,
        )
        await connect_manager.open()
        channel_id = int(f"-100{db_entity.entity_id}")
        async with connect_manager.get_client() as client:
            tg_entity = await client.get_input_entity(channel_id)

        return SessionResult(db_entity, connect_manager, db_session, tg_entity)
    else:
        raise ValueError("Failed to lock subscribed session")


async def prepare_channel_and_session(
    session: AsyncSession,
    rlm: ResourceLockManager,
    channel_url: str,
    entity_id: int | None = None,
) -> SessionResult:
    """Prepare channel entity and session for data collection.

    Args:
        session: Database session
        rlm: Resource lock manager
        channel_url: URL of the Telegram channel
        entity_id: Optional entity ID if a channel exists

    Returns:
        Tuple of (entity, connect_manager, db_session, rlm_locked):
        - entity: TelegramEntity object
        - connect_manager: ConnectManager for Telegram API
        - db_session: TelegramSession object
        - tg_entity: Telegram entity object from Telegram API
    """

    db_session = None

    # Находим сущность по channel_url
    if entity_id:
        db_entity = await TelegramEntity.get_by_entity_id(session, entity_id)
    else:
        db_entity = await TelegramEntity.get_by_url(session, channel_url)

    # Находим подписанную сессию для существующей сущности
    if db_entity:
        db_session = await find_subscribed_session(session, db_entity.id)

    return (
        await _prepare_new_channel_session(
            session=session,
            rlm=rlm,
            channel_url=channel_url,
        )
        if db_entity is None or db_session is None
        else await _prepare_subscribed_session(
            db_entity=db_entity,
            db_session=db_session,
            rlm=rlm,
        )
    )


async def _save_collection_metadata(
    session: AsyncSession,
    entity_id: int,
    message_counter: int,
    metadata: TelegramMessageMetadata | None,
) -> None:
    """Save collection metadata if there are messages."""
    if message_counter > 0 and metadata is not None:
        # Проверяем, что все значения не None перед вызовом
        if (
            metadata.from_message_id is not None
            and metadata.to_message_id is not None
            and metadata.from_datetime is not None
            and metadata.to_datetime is not None
        ):
            await TelegramChannelCollection.create_collection_record(
                session=session,
                entity_id=entity_id,
                from_message_id=metadata.from_message_id,
                to_message_id=metadata.to_message_id,
                from_datetime=metadata.from_datetime,
                to_datetime=metadata.to_datetime,
                messages_count=message_counter,
            )


async def _collect_messages_for_range(
    session: AsyncSession,
    entity_id: int,
    entity: Entity,
    connect_manager: ConnectManager,
    channel_url: str,
    from_datetime: datetime,
    to_datetime: datetime,
) -> AsyncIterator[MessageResponseModel]:
    """Collect messages for a specific date range.

    Args:
        session: Database session
        entity_id: ID of the Telegram entity
        entity: Telegram entity
        connect_manager: Connection manager
        channel_url: Channel URL
        from_datetime: Start of date range
        to_datetime: End of date range

    Yields:
        Message response models
    """
    logger.info(
        "Collecting data for channel %s from %s to %s (adjusted range)",
        channel_url,
        from_datetime,
        to_datetime,
    )
    message_counter = 0
    metadata: TelegramMessageMetadata | None = None

    async for message_dict, msg_metadata in collect_messages(
        entity=entity,
        connect_manager=connect_manager,
        condition=lambda msg: from_datetime >= msg.date >= to_datetime,
    ):
        metadata = msg_metadata
        if message_dict is None:
            break
        message_counter += 1
        yield MessageResponseModel(**message_dict)

    # Сохраняем метаданные коллекции
    await _save_collection_metadata(
        session=session,
        entity_id=entity_id,
        message_counter=message_counter,
        metadata=metadata,
    )

    logger.info(
        "Collected %d messages for range %s - %s",
        message_counter,
        from_datetime,
        to_datetime,
    )


async def handle_new_channel(
    session: AsyncSession,
    rlm: ResourceLockManager,
    channel_url: str,
    datetime_offset: datetime,
    msg: NatsMessage,
) -> AsyncIterator[MessageResponseModel]:
    """Handle new channel subscription request."""
    db_session: TelegramSession | None = None
    connect_manager: ConnectManager | None = None
    try:
        # Находим сущность по channel_id
        db_entity = await TelegramEntity.get_by_url(
            session=session,
            channel_url=channel_url,
        )

        res = await prepare_channel_and_session(
            session=session,
            rlm=rlm,
            channel_url=channel_url,
            entity_id=db_entity.id if db_entity else None,
        )
        db_session = res.db_session
        connect_manager = res.connect_manager

        logger.info("Check for overlap with already collected data.")
        # Получаем текущее время как конечную точку запрашиваемого диапазона
        current_time = datetime.now(datetime_offset.tzinfo)

        # Находим непересекающиеся диапазоны, которые нужно собрать
        ranges_to_collect = (
            await TelegramChannelCollection.find_non_overlapping_ranges(
                session=session,
                entity_id=res.tg_entity.id,
                from_datetime=datetime_offset,
                to_datetime=current_time,
            )
        )

        if not ranges_to_collect:
            # Если нет диапазонов для сбора, значит все данные уже собраны
            logger.info(
                "All data for channel %s from %s to %s "
                "has already been collected",
                channel_url,
                datetime_offset,
                current_time,
            )
            await msg.ack()
            return

        for from_datetime, to_datetime in ranges_to_collect:
            async for message in _collect_messages_for_range(
                session=session,
                entity_id=res.tg_entity.id,
                entity=res.tg_entity,
                connect_manager=connect_manager,
                channel_url=channel_url,
                from_datetime=from_datetime,
                to_datetime=to_datetime,
            ):
                yield message

        # Подтверждаем сообщение после обработки всех диапазонов
        await msg.ack()
        logger.info(
            "All ranges processed successfully for channel %s", channel_url
        )
    finally:
        if connect_manager is not None:
            await connect_manager.close()
        # Освобождаем сессию, если она была заблокирована
        if db_session and db_session.id:
            try:
                await rlm.unlock(db_session.id)
            except KeyValueError:
                logger.warning(
                    "Failed to unlock session %s, session is already unlocked",
                    db_session.id,
                )
