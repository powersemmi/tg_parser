import logging

from telethon import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.tl.types.messages import ChannelMessages

from tg_chat_parser.settings import settings

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
        total_messages_count += len(messages)
        offset_msg_id = messages[-1].id
        for message in messages:
            logger.info(message.to_dict())
