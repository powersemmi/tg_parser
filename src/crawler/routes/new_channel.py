import logging
from collections.abc import AsyncIterator
from logging import Logger
from typing import Annotated

from fast_depends import Depends
from faststream import Context
from faststream.nats import JStream, NatsMessage, NatsRouter
from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy
from sqlalchemy.ext.asyncio import AsyncSession

from common.utils.nats.resource_manager import ResourceLockManager
from crawler.database.pg.db import get_session
from crawler.procedures.new_channel import handle_new_channel
from crawler.schemas.message import MessageResponseModel
from crawler.schemas.new_channel import NewChannelParseMessageBody
from crawler.settings import settings

router: NatsRouter = NatsRouter()

logger: Logger = logging.getLogger(__name__)


@router.subscriber(
    "new_channel",
    stream=JStream(name=settings.NATS_STREAM),
    config=ConsumerConfig(
        durable_name="new_channel_consumer",
        deliver_subject="new_channel.dlq",
        ack_policy=AckPolicy.EXPLICIT,
        deliver_policy=DeliverPolicy.NEW,
        max_deliver=settings.NATS_MAX_DELIVERED_MESSAGES_COUNT,
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
    rlm: Annotated[ResourceLockManager, Depends(Context)],
) -> AsyncIterator[MessageResponseModel]:
    """Обработчик запросов на обработку новых каналов Telegram.

    Эндпоинт NATS для обработки новых каналов Telegram. Подписывается на тему
    "new_channel" и публикует собранные сообщения в настраиваемую тему,
    указанную в settings.MESSAGE_SUBJECT.

    Использует функцию handle_new_channel из модуля procedures для подготовки
    сессии, сбора сообщений из указанного канала за заданный период времени,
    обработки ошибок и подтверждения успешной обработки.

    Args:
        body: Тело запроса, содержащее URL канала и другие параметры
        msg: Объект сообщения NATS
        session: Сессия базы данных
        rlm: Менеджер блокировки ресурсов

    Yields:
        Пакеты обработанных сообщений в формате MessageResponseModel
    """

    channel_url = body.channel_url.unicode_string()
    try:
        logger.info(
            "Processing scheduled task for channel_url=%s datetime_offset=%s",
            body.channel_url,
            body.datetime_offset,
        )
        async for message_response in handle_new_channel(
            session=session,
            rlm=rlm,
            channel_url=channel_url,
            datetime_offset=body.datetime_offset,
            msg=msg,
        ):
            yield message_response

    except Exception as e:
        logger.error("Error processing scheduled task: %s", e, exc_info=True)
        await msg.nack()
