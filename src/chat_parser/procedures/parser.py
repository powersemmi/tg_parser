import asyncio
import hashlib
import logging
from datetime import datetime

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession
from telethon import TelegramClient
from telethon.tl.types import Message

from chat_parser.database.shemas.message import get_channel_table
from chat_parser.settings import settings

logger = logging.getLogger(__name__)


async def parse(
    client: TelegramClient,
    session: AsyncSession,
    channel_url: str,
    message_limit: int,
    offset_msg_id: int | None = None,
    offset_date: datetime | None = None,
    from_user: str | None = None,
    filter: None = None,
    search: str | None = None,
    reverse: bool = True,
) -> None:
    channel = await client.get_entity(channel_url)
    table = await get_channel_table(
        session=session,
        schema=settings.PG_DSN.path[1:]
        if settings.PG_DSN.path is not None
        else "app",
        name=hashlib.sha256(string=channel_url.encode()).hexdigest()[:-1],
    )
    res: list[Message] = await client.get_messages(
        channel,
        limit=message_limit,
        # offset_date=offset_date,
        # offset_id=offset_msg_id,
        reverse=reverse,
    )
    messages_to_create = [
        {"raw": i.to_dict(), "date": i.to_dict()["date"]} for i in res
    ]
    await session.execute(insert(table), messages_to_create)
    await session.commit()
