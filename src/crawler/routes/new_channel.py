"""Router for handling new channel subscription requests.

Provides endpoints for processing new Telegram channels.
"""

import logging
from collections.abc import AsyncIterator
from datetime import datetime
from logging import Logger
from typing import Annotated, Any

from fast_depends import Depends
from faststream import Context
from faststream.nats import JStream, NatsMessage, NatsRouter
from gunicorn.config import User
from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy
from nats.js.errors import KeyValueError
from sqlalchemy.ext.asyncio import AsyncSession
from telethon.hints import Entity
from telethon.tl.types import Channel, Chat

from common.utils.nats.resource_manager import ResourceLockManager
from crawler.database.pg.db import get_session
from crawler.database.pg.queries.session_entity import find_subscribed_session
from crawler.database.pg.schemas import TelegramEntity, TelegramSession
from crawler.database.pg.schemas.telegram.collections import (
    TelegramChannelCollection,
)
from crawler.database.tg import ConnectManager
from crawler.procedures.parser import TelegramMessageMetadata
from crawler.procedures.schedule import collect_messages
from crawler.schemas.message import MessageResponseModel
from crawler.schemas.new_channel import NewChannelParseMessageBody
from crawler.settings import settings

router: NatsRouter = NatsRouter()

logger: Logger = logging.getLogger(__name__)


@router.subscriber(
    "new_channel",
    stream=JStream(name=settings.NATS_JSTREAM),
    config=ConsumerConfig(
        durable_name="new_channel_consumer",
        deliver_subject="new_channel.dlq",
        ack_policy=AckPolicy.EXPLICIT,
        deliver_policy=DeliverPolicy.NEW,
        max_deliver=3,
        max_ack_pending=1,
    ),
)
@router.publisher(
    subject=settings.MESSAGE_SUBJECT,
    stream=JStream(name=settings.MESSAGE_STREAM),
)
async def handle_new_channels(
    body: NewChannelParseMessageBody,
    msg: NatsMessage,
    session: Annotated[AsyncSession, Depends(get_session, use_cache=False)],
    rlm: Annotated[ResourceLockManager, Depends(Context())],
) -> AsyncIterator[MessageResponseModel]:
    """Handle requests for processing new channels.

    Processes messages from new Telegram channels and sends them in batches.

    Args:
        body: Request body containing channel URL and other parameters
        msg: NATS message object
        session: Database session
        rlm: Resource lock manager

    Yields:
        Batches of processed messages
    """
    db_session: TelegramSession | None = None
    rlm_locked: bool = False
    connect_manager: ConnectManager | None = None

    channel_url = body.channel_url.unicode_string()
    try:
        logger.info(
            "Processing scheduled task for channel_url=%s datetime_offset=%s",
            body.channel_url,
            body.datetime_offset,
        )
        # Находим сущность по channel_id
        db_entity = await TelegramEntity.get_by_url(
            session=session,
            channel_url=channel_url,
        )
        if db_entity:
            db_session = await find_subscribed_session(session, db_entity.id)
            if db_session and await rlm.lock(db_session.id):
                rlm_locked = True
                logger.info(
                    "Successfully acquired session %s "
                    "already subscribed to channel %s",
                    db_session.id,
                    db_entity.entity_url,
                )
                # noinspection PyTypeChecker
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
        else:
            async with rlm.session() as db_session_id:
                db_session = await TelegramSession.get(
                    session=session, id=db_session_id
                )
                if db_session is None:
                    await rlm.update_resources(
                        await TelegramSession.get_all_id(session=session)
                    )
                    await msg.nack()
                    logger.warning(
                        "Session %s not found, update local sessions",
                        db_session_id,
                    )
                    raise ValueError(f"Session {db_session_id} not found")
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
                    raise ValueError(
                        f"Неизвестный тип сущности: {type(tg_entity)}"
                    )
                await TelegramEntity.create_entity(
                    session=session,
                    channel_url=body.channel_url.unicode_string(),
                    entity_id=entity_id,
                    entity_name=entity_name,
                )
                await session.commit()

        logger.info("Check for overlap with already collected data.")
        # Получаем текущее время как конечную точку запрашиваемого диапазона
        current_time = datetime.now(body.datetime_offset.tzinfo)

        # Находим непересекающиеся диапазоны, которые нужно собрать
        ranges_to_collect = (
            await TelegramChannelCollection.find_non_overlapping_ranges(
                session=session,
                entity_id=tg_entity.id,
                from_datetime=body.datetime_offset,
                to_datetime=current_time,
            )
        )

        if not ranges_to_collect:
            # Если нет диапазонов для сбора, значит все данные уже собраны
            logger.info(
                "All data for channel %s from %s to %s has already been collected",
                channel_url,
                body.datetime_offset,
                current_time,
            )
            await msg.ack()
            return

        for from_datetime, to_datetime in ranges_to_collect:
            logger.info(
                "Collecting data for channel %s from %s to %s (adjusted range)",
                channel_url,
                from_datetime,
                to_datetime,
            )
            # Собираем сообщения
            message_counter = 0
            metadata: TelegramMessageMetadata | None = None

            async for message_dict, msg_metadata in collect_messages(
                entity=tg_entity,
                connect_manager=connect_manager,
                condition=lambda msg: msg.id <= body.last_message_id,
            ):
                metadata = msg_metadata
                if message_dict is None:
                    break
                message_counter += 1
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
        if connect_manager is not None:
            await connect_manager.close()
        # Освобождаем сессию если она была заблокирована
        if rlm_locked and db_session and db_session.id:
            try:
                await rlm.unlock(db_session.id)
            except KeyValueError:
                logger.warning(
                    "Failed to unlock session %s, session is already unlocked",
                    db_session.id,
                )
