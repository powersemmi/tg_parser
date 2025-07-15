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
from crawler.database.pg.schemas import TelegramSession
from crawler.procedures.schedule import handle_schedule
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
async def handle_schedules(
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
        async for message_response in handle_schedule(
            session=session,
            rlm=rlm,
            channel_id=body.channel_id,
            last_message_id=body.last_message_id,
            msg=msg,
        ):
            yield message_response
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
