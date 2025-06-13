import hashlib
import logging
from datetime import datetime

from clickhouse_connect.driver import AsyncClient
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession
from telethon.tl.types import Message

from crawler.database.pg.shemas import get_channel_table
from crawler.database.tg import TelethonClientManager
from crawler.settings import settings

logger = logging.getLogger(__name__)


async def crawl_telegram_messages(
    session: AsyncSession,
    client: AsyncClient,
    tcm: TelethonClientManager,
    channel_url: str,
    message_limit: int,
    offset_msg_id: int | None = None,
    offset_date: datetime | None = None,
    from_user: str | None = None,
    filter: None = None,
    search: str | None = None,
    reverse: bool = True,
) -> None:
    async with tcm.get_client() as tg_client:
        channel = await tg_client.get_entity(channel_url)
    table = await get_channel_table(
        session=session,
        schema=settings.PG_DSN.path[1:]
        if settings.PG_DSN.path is not None
        else "app",
        name=hashlib.sha256(string=channel_url.encode()).hexdigest()[:-1],
    )
    res: list[Message] = await tg_client.get_messages(
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
