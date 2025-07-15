import logging
from collections.abc import AsyncIterator

from faststream.nats import NatsMessage
from sqlalchemy.ext.asyncio import AsyncSession
from telethon.hints import Entity

from common.utils.nats.resource_manager import ResourceLockManager
from crawler.database.pg.queries.session_entity import find_subscribed_session
from crawler.database.pg.schemas import TelegramEntity, TelegramSession
from crawler.database.pg.schemas.telegram.collections import (
    TelegramChannelCollection,
)
from crawler.database.tg import ConnectManager
from crawler.procedures.parser import TelegramMessageMetadata, collect_messages
from crawler.schemas.message import MessageResponseModel
from crawler.settings import settings

logger = logging.getLogger(__name__)


async def _get_telegram_entity(
    session: AsyncSession, channel_id: int, msg: NatsMessage
) -> TelegramEntity | None:
    """Получение Telegram сущности по ID канала.

    Args:
        session: Сессия базы данных
        channel_id: ID канала
        msg: NATS сообщение для подтверждения

    Returns:
        Сущность Telegram или None в случае ошибки
    """
    tg_entity = await TelegramEntity.get_by_entity_id(session, channel_id)
    if not tg_entity:
        logger.error(f"Entity not found for channel_id={channel_id}")
        await (
            msg.ack()
        )  # Подтверждаем сообщение, т.к. повторная обработка не поможет
        return None
    return tg_entity


async def _get_and_lock_session(
    session: AsyncSession,
    rlm: ResourceLockManager,
    entity_id: int,
    msg: NatsMessage,
) -> TelegramSession | None:
    """Получение и блокировка сессии Telegram.

    Args:
        session: Сессия базы данных
        rlm: Менеджер ресурсов
        entity_id: ID сущности
        msg: NATS сообщение

    Returns:
        Сессия Telegram или None в случае ошибки
    """
    # Получаем данные сессии
    db_entity = await find_subscribed_session(session, entity_id)
    if db_entity is None:
        logger.error("Session %s not found", entity_id)
        await (
            msg.ack()
        )  # Подтверждаем сообщение, т.к. повторная обработка не поможет
        return None

    # Блокируем сессию через resource manager
    if (
        not await rlm.lock(db_entity.id)
        and msg.raw_message.metadata.num_delivered
        < settings.NATS_MAX_DELIVERED_MESSAGES_COUNT
    ):
        logger.error("Failed to lock session %s", db_entity.id)
        await msg.nack()
        return None

    # Получаем сессию из пула
    db_entity_id = await rlm.session().__aenter__()
    db_entity = await TelegramSession.get(session, id=db_entity_id)
    if db_entity is None:
        logger.error("Session %s not found", db_entity_id)
        await msg.nack()
        return None

    return db_entity


async def _get_telegram_input_entity(
    connect_manager: ConnectManager,
    entity_id: int,
    channel_id: int,
    msg: NatsMessage,
) -> Entity | None:
    """Получение Telegram input entity.

    Args:
        connect_manager: Менеджер соединения
        entity_id: ID сущности
        channel_id: ID канала для сообщений об ошибках
        msg: NATS сообщение

    Returns:
        Telegram сущность или None в случае ошибки
    """
    try:
        channel_id_formatted = int(f"-100{entity_id}")
        async with connect_manager.get_client() as client:
            return await client.get_input_entity(channel_id_formatted)
    except ValueError:
        await msg.nack()
        logger.error("Invalid channel_id: %s", channel_id)
        return None


async def _save_collection_metadata(
    session: AsyncSession,
    entity_id: int,
    metadata: TelegramMessageMetadata,
    message_counter: int,
) -> None:
    """Сохранение метаданных коллекции сообщений.

    Args:
        session: Сессия базы данных
        entity_id: ID сущности
        metadata: Метаданные сообщений
        message_counter: Количество собранных сообщений
    """
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


async def _collect_messages(
    tg_entity: Entity,
    connect_manager: ConnectManager,
    last_message_id: int,
    session: AsyncSession,
) -> AsyncIterator[
    tuple[MessageResponseModel, TelegramMessageMetadata | None, int]
]:
    """Сбор сообщений из Telegram.

    Args:
        tg_entity: Telegram сущность
        connect_manager: Менеджер соединения
        last_message_id: ID последнего сообщения
        session: Сессия базы данных

    Yields:
        Кортеж из (сообщение, метаданные, счетчик сообщений)
    """
    message_counter = 0
    metadata: TelegramMessageMetadata | None = None

    async for message_dict, msg_metadata in collect_messages(
        entity=tg_entity,
        connect_manager=connect_manager,
        condition=lambda msg: msg.id <= last_message_id,
    ):
        metadata = msg_metadata
        if message_dict is None:
            break
        message_counter += 1
        # Преобразуем MessageDict в MessageResponseModel
        yield MessageResponseModel(**message_dict), metadata, message_counter


async def handle_schedule(
    session: AsyncSession,
    rlm: ResourceLockManager,
    channel_id: int,
    last_message_id: int,
    msg: NatsMessage,
) -> AsyncIterator[MessageResponseModel]:
    logger.info(
        "Processing scheduled task for channel_id=%s from_message_id=%s",
        channel_id,
        last_message_id,
    )

    # Получаем сущность и сессию
    tg_entity = await _get_telegram_entity(session, channel_id, msg)
    if not tg_entity:
        return

    db_entity = await _get_and_lock_session(
        session, rlm, tg_entity.entity_id, msg
    )
    if not db_entity:
        return

    # Создаем connect manager для работы с Telegram API
    async with ConnectManager(
        session=db_entity.session,
        api_id=db_entity.api_id,
        api_hash=db_entity.api_hash,
        proxy=db_entity.proxy,
    ) as connect_manager:
        # Получаем Telegram сущность
        input_entity = await _get_telegram_input_entity(
            connect_manager, tg_entity.entity_id, channel_id, msg
        )
        if not input_entity:
            return

        # Собираем сообщения
        message_counter = 0
        last_metadata = None

        async for message, metadata, counter in _collect_messages(
            input_entity, connect_manager, last_message_id, session
        ):
            message_counter = counter
            last_metadata = metadata
            yield message

        # Сохраняем метаданные коллекции
        if last_metadata:
            await _save_collection_metadata(
                session, tg_entity.id, last_metadata, message_counter
            )

        await msg.ack()
        logger.info(
            "Scheduled task processed successfully. Collected %d messages",
            message_counter,
        )
