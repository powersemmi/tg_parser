import logging
from typing import Annotated

from clickhouse_connect.driver import AsyncClient
from fast_depends import Depends
from faststream import Context
from faststream.nats import JStream, NatsRouter
from nats.js.api import DeliverPolicy
from sqlalchemy.ext.asyncio import AsyncSession

from chat_parser.database.ch.db import get_client
from chat_parser.database.pg.db import get_session
from chat_parser.database.tg import TelethonClientManager
from chat_parser.procedures.parser import crawl_telegram_messages
from chat_parser.schemas.parser import ParseMessageBody

router = NatsRouter(prefix="chat_parser.")
stream = JStream(name="stream")

logger = logging.getLogger(__name__)


@router.subscriber(
    "tg-crawler-subject",
    stream=stream,
    deliver_policy=DeliverPolicy.NEW,
)
async def handler(
    body: ParseMessageBody,
    session: Annotated[AsyncSession, Depends(get_session, use_cache=False)],
    client: Annotated[AsyncClient, Depends(get_client, use_cache=False)],
    tcm: Annotated[TelethonClientManager, Depends(Context())],
) -> None:
    try:
        await crawl_telegram_messages(
            session=session,
            client=client,
            tcm=tcm,
            channel_url=str(body.channel_url),
            message_limit=body.massage_limit,
            offset_msg_id=body.offset_msg_id,
            offset_date=body.date_offset,
        )
    except Exception as e:
        logger.error("Found exception! %s", e, exc_info=True)
