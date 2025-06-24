import logging
from typing import Annotated

from fast_depends import Depends
from faststream.nats import NatsMessage, NatsRouter
from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy
from sqlalchemy.ext.asyncio import AsyncSession

from crawler.brokers import parser_stream
from crawler.database.pg.db import get_session
from crawler.schemas.new_channel import NewChannelParseMessageBody
from crawler.settings import settings

router = NatsRouter(prefix=settings.NATS_PREFIX)

logger = logging.getLogger(__name__)


@router.subscriber(
    "new_channel",
    stream=parser_stream,
    config=ConsumerConfig(
        durable_name="new_channel_consumer",
        deliver_subject=f"{settings.NATS_PREFIX}.new_channel.dlq",
        ack_policy=AckPolicy.EXPLICIT,
        deliver_policy=DeliverPolicy.NEW,
        max_deliver=3,
        max_ack_pending=1,
    ),
)
async def handle_new_channels(
    body: NewChannelParseMessageBody,
    msg: NatsMessage,
    session: Annotated[AsyncSession, Depends(get_session, use_cache=False)],
) -> None:
    try:
        await msg.ack()
    except Exception as e:
        logger.error("Found exception! %s", e, exc_info=True)
        await msg.nack()
