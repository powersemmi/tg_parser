"""PostgreSQL database connection configuration module.

Provides connection utilities and session factory for PostgreSQL database.
"""

import logging
from collections.abc import AsyncGenerator
from logging import Logger
from typing import Any

import orjson
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from crawler.settings import settings

logger: Logger = logging.getLogger(__name__)


def orjson_default(obj: Any) -> str | None:
    """Default serializer for types not natively supported by orjson.

    Args:
        obj: Object to serialize

    Returns:
        Empty string for bytes objects, None otherwise
    """
    if isinstance(obj, bytes):
        logger.info("PASS BYTES")
        return ""
    return None


def orjson_serializer(obj: Any) -> str:
    """JSON serializer for SQLAlchemy using orjson.

    Note that `orjson.dumps()` returns byte array, while SQLAlchemy expects
    string, thus `decode()` call is necessary.

    Args:
        obj: Object to serialize to JSON

    Returns:
        JSON string representation of the object
    """
    return orjson.dumps(
        obj,
        option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NAIVE_UTC,
        default=orjson_default,
    ).decode()


engine = create_async_engine(
    str(settings.PG_DSN),
    echo=settings.DEBUG,
    echo_pool=settings.DEBUG,
    hide_parameters=not settings.DEBUG,
    pool_size=settings.PG_POOL_SIZE,
    max_overflow=settings.PG_MAX_POOL_SIZE,
    pool_pre_ping=True,
    pool_recycle=3600,
    json_deserializer=orjson.dumps,
    json_serializer=orjson_serializer,
)

async_session = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession]:
    """Create and yield a database session.

    Manages session lifecycle with automatic rollback on exceptions.

    Yields:
        Database session object

    Raises:
        Exception: Propagates any exceptions after session rollback
    """
    async with async_session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
