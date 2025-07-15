import logging
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from logging import Logger

from faststream import ContextRepo, FastStream
from logging518 import config

from common.utils.nats.resource_manager import ResourceLockManager
from crawler.brokers import broker
from crawler.database.pg.db import async_session
from crawler.database.pg.schemas.telegram.sessions import TelegramSession
from crawler.routes import new_channel, schedule
from crawler.settings import settings

sys.excepthook = sys.__excepthook__
logger: Logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(context: ContextRepo) -> AsyncGenerator[None]:
    """Application lifecycle manager.

    Sets up resources and manages their lifecycle during application runtime.

    Args:
        context: Repository for sharing context across the application

    Yields:
        Control back to the application server
    """
    async with async_session() as session:
        resource_ids = await TelegramSession.get_all_id(session=session)
    async with broker:
        await broker.publish(
            "test", subject="new_channel", stream="CHAT_PARSER"
        )
        async with ResourceLockManager(
            broker=broker,
            key_prefix=settings.NATS_PREFIX,
            resource_ids=resource_ids,
            kv_bucket=settings.NATS_KV_BUCKET,
            instance_id=settings.POD_NAME,
            ttl=settings.NATS_KV_TTL,
        ) as rlm:
            context.set_global("rlm", rlm)
            yield


def create_app() -> FastStream:
    """Create and configure the FastStream application.

    Returns:
        Configured FastStream application instance
    """
    application = FastStream(
        broker=broker,
        title=settings.APP_NAME.title().replace("-", " "),
        logger=logger,
        version="1.0.0",
        lifespan=lifespan,
    )

    broker.include_router(new_channel.router)
    broker.include_router(schedule.router)

    return application


config.fileConfig("pyproject.toml")
app: FastStream = create_app()
