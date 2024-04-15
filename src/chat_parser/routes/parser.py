import logging
from typing import Annotated

from fast_depends import Depends
from faststream.rabbit import RabbitRouter
from sqlalchemy.ext.asyncio import AsyncSession
from telethon import TelegramClient

from chat_parser.database.db import get_session
from chat_parser.database.telegram import get_telegram_client
from chat_parser.procedures.parser import parse
from chat_parser.schemas.parser import ParseMessage

router = RabbitRouter(prefix="chat_parser.")

logger = logging.getLogger(__name__)


@router.subscriber(queue="in")
async def parser_handler(
    body: ParseMessage,
    session: Annotated[AsyncSession, Depends(get_session, use_cache=False)],
    telegram: Annotated[TelegramClient, Depends(get_telegram_client)],
) -> None:
    try:
        await parse(
            client=telegram,
            session=session,
            channel_url=str(body.channel_url),
            message_limit=body.massage_limit,
            offset_msg_id=body.offset_msg_id,
            offset_date=body.date_offset,
        )
    except Exception as e:
        logger.error("Found exception! %s", e, exc_info=True)
