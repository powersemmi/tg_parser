import asyncio
import logging
from collections.abc import AsyncGenerator, Callable

import asyncstdlib
from telethon.tl.custom.message import Message

logger = logging.getLogger(__name__)


async def _iter_messages_locked(entity: int) -> AsyncGenerator[Message, None]:
    async with TGSessionManager.client_session() as client:
        async for message in client.iter_messages(
            entity=entity, reverse=False
        ):
            yield message


async def try_find_channel_id(): ...


async def crawl_messages(
    channel: FashionChannel,
    s3_client: BaseClient,
    bucket: str,
    condition: Callable[[Message], bool],
) -> None:
    """
    Функция ходит с последнего сообщения в чате до тех пор, пока
    не удовлетворит condition и сохраняет текст сообщений в базу

    :param bucket: Бакет для s3
    :param s3_client: Клиент s3
    :param entity: Объект идентифицирующий чат в Telegram.
    :param channel: Объект с информацией о канале.
    :param condition: Функция, которая определяет когда сбору прекратиться,
                      в случае если функция всегда будет
                      возвращать False, сбор будет происходить до тех пор,
                      пока функция не дойдёт до начала канала
    """
    counter = 0
    tasks = []
    channel_id = int(f"-100{channel.id}")
    async with TGSessionManager.client_session() as client:
        try:
            entity = await client.get_input_entity(channel_id)
        except ValueError:
            entity = await client.get_entity(channel.url)
    async for counter, message in asyncstdlib.enumerate(
        _iter_messages_locked(entity=entity)
    ):
        try:
            if condition(message):
                break
            tasks.append(
                asyncio.create_task(
                    _handle_message_result(
                        channel=channel,
                        s3_client=s3_client,
                        bucket=bucket,
                        message=message,
                    )
                )
            )
        except Exception as e:
            logger.info(e, exc_info=True)
    await asyncio.gather(*tasks)
    logger.info("Processed %s messages", counter)
