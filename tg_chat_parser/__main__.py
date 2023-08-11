import asyncio

import logging518.config
from telethon import TelegramClient

from tg_chat_parser.crawler import worker
from tg_chat_parser.settings import settings


async def main() -> None:
    tg_client: TelegramClient = TelegramClient(
        "Crawler",
        api_id=settings.TG_API_ID,
        api_hash=settings.TG_API_HASH,
        auto_reconnect=True,
        sequential_updates=True,
        lang_code="ru",
    )
    async with tg_client:
        await worker(client=tg_client)


if __name__ == "__main__":
    logging518.config.fileConfig("pyproject.toml")
    asyncio.run(main())
