import logging
from collections.abc import AsyncGenerator

from telethon import TelegramClient

from chat_parser.settings import settings

logger = logging.getLogger(__name__)


async def get_telegram_client() -> AsyncGenerator[TelegramClient, None]:
    client: TelegramClient = TelegramClient(
        session=settings.TG_SESSION_NAME,
        api_id=settings.TG_API_ID,
        api_hash=settings.TG_API_HASH,
        auto_reconnect=True,
        sequential_updates=True,
        lang_code="ru",
    )
    try:
        await client.connect()
        if not await client.is_user_authorized():
            logger.info("User not authenticate!")
            await client.start(
                settings.TG_PHONE_NUMBER, password=settings.TG_PASSWORD
            )
        yield client
    finally:
        await client.disconnect()
