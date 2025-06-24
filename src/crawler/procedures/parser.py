import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from telethon.tl.custom.message import Message

from crawler.database.pg.shemas.telegram.sessions import TelegramSession

logger = logging.getLogger(__name__)


async def try_find_channel_id() -> None: ...


async def crawl_messages(
    tg_session: TelegramSession,
    condition: Callable[[Message], bool],
) -> None:
    counter = 0
    tasks: list[Awaitable[Any]] = []
    # channel_id = int(f"-100{channel.id}")
    # async with TGSessionManager.client_session() as tg_session:
    #     try:
    #         entity = await tg_session.get_input_entity(channel_id)
    #     except ValueError:
    #         entity = await tg_session.get_entity(channel.url)
    # async for counter, message in asyncstdlib.enumerate(
    #     client.iter_messages(entity=entity, reverse=False)
    # ):
    #     try:
    #         if condition(message):
    #             break
    #         tasks.append(
    #             asyncio.create_task(
    #                 _handle_message_result(
    #                     channel=channel,
    #                     s3_client=s3_client,
    #                     bucket=bucket,
    #                     message=message,
    #                 )
    #             )
    #         )
    #     except Exception as e:
    #         logger.info(e, exc_info=True)
    await asyncio.gather(*tasks)
    logger.info("Processed %s messages", counter)
