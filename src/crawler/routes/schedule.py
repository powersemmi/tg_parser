"""Router for handling scheduled task requests.

Provides endpoints for processing scheduled parsing tasks.
"""

import logging
from collections.abc import AsyncIterator
from logging import Logger
from typing import Annotated

from fast_depends import Depends
from faststream import Context
from faststream.nats import JStream, NatsMessage, NatsRouter
from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy
from nats.js.errors import KeyValueError
from sqlalchemy.ext.asyncio import AsyncSession

from common.utils.nats.resource_manager import ResourceLockManager
from crawler.database.pg.db import get_session
from crawler.database.pg.queries.session_entity import find_subscribed_session
from crawler.database.pg.schemas import TelegramSession
from crawler.database.pg.schemas.telegram.collections import (
    TelegramChannelCollection,
)
from crawler.database.pg.schemas.telegram.entities import TelegramEntity
from crawler.database.tg import ConnectManager
from crawler.procedures.parser import TelegramMessageMetadata, collect_messages
from crawler.schemas.message import MessageResponseModel
from crawler.schemas.schedule import ScheduleParseMessageSchema
from crawler.settings import settings

router: NatsRouter = NatsRouter()

logger: Logger = logging.getLogger(__name__)


@router.subscriber(
    "schedule",
    stream=JStream(name=settings.NATS_PREFIX),
    config=ConsumerConfig(
        durable_name="schedule_consumer",
        deliver_subject="schedule.dlq",
        ack_policy=AckPolicy.EXPLICIT,
        deliver_policy=DeliverPolicy.NEW,
        max_deliver=settings.NATS_MAX_DELIVERED_MESSAGES_COUNT,
        max_ack_pending=1,
    ),
)
@router.publisher(
    "messages",
    stream=JStream(
        name=settings.NATS_PREFIX,
        subjects=["messages"],
    ),
)
async def handle_schedule(
    body: ScheduleParseMessageSchema,
    msg: NatsMessage,
    session: Annotated[AsyncSession, Depends(get_session, use_cache=False)],
    rlm: Annotated[ResourceLockManager, Depends(Context())],
) -> AsyncIterator[MessageResponseModel]:
    """Handle scheduled parsing tasks.

    Processes scheduled messages for content parsing.

    Args:
        body: Request body containing schedule parameters
        msg: NATS message object
        session: Database session
        rlm: Resource lock manager

    Returns:
        list[MessageResponseModel]: Список собранных сообщений для
            отправки в ClickHouse
    """
    db_entity: TelegramSession | None = None
    try:
        logger.info(
            "Processing scheduled task for channel_id=%s from_message_id=%s",
            body.channel_id,
            body.from_message_id,
        )
        # Находим сущность по channel_id
        tg_entity = await TelegramEntity.get_by_entity_id(
            session,
            body.channel_id,
        )
        if not tg_entity:
            logger.error(f"Entity not found for channel_id={body.channel_id}")
            await (
                msg.ack()
            )  # Подтверждаем сообщение, т.к. повторная обработка не поможет
            return

        # Получаем данные сессии
        db_entity = await find_subscribed_session(session, tg_entity.entity_id)
        if db_entity is None:
            logger.error("Session %s not found", tg_entity.entity_id)
            await (
                msg.ack()
            )  # Подтверждаем сообщение, т.к. повторная обработка не поможет
            return

        # Блокируем сессию через resource manager
        if (
            not await rlm.lock(db_entity.id)
            and msg.raw_message.metadata.num_delivered
            < settings.NATS_MAX_DELIVERED_MESSAGES_COUNT
        ):
            logger.error("Failed to lock session %s", db_entity.id)
            await msg.nack()
            return
        else:
            db_entity_id = await rlm.session().__aenter__()
            db_entity = await TelegramSession.get(session, id=db_entity_id)
            if db_entity is None:
                logger.error("Session %s not found", db_entity_id)
                await msg.nack()

        # Создаем connect manager для работы с Telegram API
        async with ConnectManager(
            session=db_entity.session,
            api_id=db_entity.api_id,
            api_hash=db_entity.api_hash,
            proxy=db_entity.proxy,
        ) as connect_manager:
            # Собираем сообщения
            message_counter = 0
            metadata: TelegramMessageMetadata | None = None

            # Получаем сущность
            try:
                channel_id = int(f"-100{tg_entity.entity_id}")
                async with connect_manager.get_client() as client:
                    tg_entity = await client.get_input_entity(channel_id)
            except ValueError:
                await msg.nack()
                logger.error("Invalid channel_id: %s", body.channel_id)
                return

            async for message_dict, msg_metadata in collect_messages(
                entity=tg_entity,
                connect_manager=connect_manager,
                condition=lambda msg: msg.id <= body.last_message_id,
            ):
                metadata = msg_metadata
                if message_dict is None:
                    break
                message_counter += 1
                # Преобразуем MessageDict в MessageResponseModel
                yield MessageResponseModel(**message_dict)

            # Сохраняем метаданные коллекции если есть сообщения
            if message_counter > 0 and metadata is not None:
                await TelegramChannelCollection.create_collection_record(
                    session=session,
                    entity_id=tg_entity.id,
                    from_message_id=metadata.from_message_id,
                    to_message_id=metadata.to_message_id,
                    from_datetime=metadata.from_datetime,
                    to_datetime=metadata.to_datetime,
                    messages_count=message_counter,
                )

            await msg.ack()
            logger.info(
                "Scheduled task processed successfully. Collected %d messages",
                message_counter,
            )
    except Exception as e:
        logger.error("Error processing scheduled task: %s", e, exc_info=True)
        await msg.nack()
    finally:
        # Освобождаем сессию если она была заблокирована
        if db_entity and db_entity.id:
            try:
                await rlm.unlock(db_entity.id)
            except KeyValueError:
                logger.warning(
                    "Failed to unlock session %s, session is already unlocked",
                    db_entity.id,
                )
