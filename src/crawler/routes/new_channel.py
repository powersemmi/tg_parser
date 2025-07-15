"""Router for handling new channel subscription requests.

Provides endpoints for processing new Telegram channels.
"""

import logging
from collections.abc import AsyncIterator
from datetime import datetime
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
from crawler.database.pg.schemas import TelegramEntity, TelegramSession
from crawler.database.pg.schemas.telegram.collections import (
    TelegramChannelCollection,
)
from crawler.database.tg import ConnectManager
from crawler.procedures.new_channels import prepare_channel_and_session
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

        res = await prepare_channel_and_session(
            session=session,
            rlm=rlm,
            channel_url=channel_url,
            entity_id=db_entity.id,
        )
        db_session = res.db_session
        connect_manager = res.connect_manager

        logger.info("Check for overlap with already collected data.")
        # Получаем текущее время как конечную точку запрашиваемого диапазона
        current_time = datetime.now(body.datetime_offset.tzinfo)

        # Находим непересекающиеся диапазоны, которые нужно собрать
        ranges_to_collect = (
            await TelegramChannelCollection.find_non_overlapping_ranges(
                session=session,
                entity_id=res.tg_entity.id,
                from_datetime=body.datetime_offset,
                to_datetime=current_time,
            )
        )

        if not ranges_to_collect:
            # Если нет диапазонов для сбора, значит все данные уже собраны
            logger.info(
                "All data for channel %s from %s to %s has already "
                "been collected",
                channel_url,
                body.datetime_offset,
                current_time,
            )
            await msg.ack()
            return

        for from_datetime, to_datetime in ranges_to_collect:
            logger.info(
                "Collecting data for channel %s from %s to %s "
                "(adjusted range)",
                channel_url,
                from_datetime,
                to_datetime,
            )
            # Собираем сообщения
            message_counter = 0
            metadata: TelegramMessageMetadata | None = None

            async for message_dict, msg_metadata in collect_messages(
                entity=res.tg_entity,
                connect_manager=res.connect_manager,
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
                    entity_id=res.tg_entity.id,
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
        if db_session and db_session.id:
            try:
                await rlm.unlock(db_session.id)
            except KeyValueError:
                logger.warning(
                    "Failed to unlock session %s, session is already unlocked",
                    db_session.id,
                )
