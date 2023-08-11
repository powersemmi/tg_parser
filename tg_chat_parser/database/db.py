import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

import orjson
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tg_chat_parser.settings import settings


def orjson_serializer(obj: Any) -> str:
    """
    Note that `orjson.dumps()` return byte array, while sqlalchemy expects string, thus `decode()` call.
    """
    return orjson.dumps(
        obj, option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NAIVE_UTC
    ).decode()


engine = create_async_engine(
    str(settings.PG_DSN),
    echo=settings.DEBUG,
    echo_pool=settings.DEBUG,
    hide_parameters=not settings.DEBUG,
    pool_size=settings.PG_POOL_SIZE,
    max_overflow=settings.PG_MAX_POOL_SIZE,
    isolation_level="SERIALIZABLE",
    pool_pre_ping=True,
    pool_recycle=3600,
    json_deserializer=orjson.dumps,
    json_serializer=orjson_serializer,
)

async_session = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session
