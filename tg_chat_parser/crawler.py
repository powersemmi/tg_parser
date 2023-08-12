import logging
from typing import TYPE_CHECKING

from telethon import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.tl.types.messages import ChannelMessages

from tg_chat_parser.database.db import get_session
from tg_chat_parser.database.shemas import Message
from tg_chat_parser.settings import settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession  # noqa:F401

logger = logging.getLogger(__name__)


async def worker(client: TelegramClient) -> None:
    channel = await client.get_entity(str(settings.CHANNEL_URL))
    total_messages_count = 0
    offset_msg_id = settings.MESSAGE_OFFSET
    while total_messages_count <= settings.MESSAGE_LIMIT:
        history: ChannelMessages = await client(
            GetHistoryRequest(
                peer=channel,  # noqa
                offset_id=offset_msg_id,
                offset_date=settings.DATE_OFFSET,
                add_offset=0,
                limit=settings.MESSAGE_REQUEST_LIMIT,
                max_id=0,
                min_id=0,
                hash=0,
            )
        )
        if not history.messages:
            break
        messages = history.messages
        if not messages:
            break
        total_messages_count += len(messages)
        offset_msg_id = messages[-1].id
        messages_to_create = []
        for message in messages:
            message_dict = message.to_dict()
            logger.info(message_dict)
            messages_to_create.append(Message(message_raw=message_dict))
        async with get_session() as session:  # type: AsyncSession
            session.add_all(messages_to_create)
            await session.commit()
