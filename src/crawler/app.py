import asyncio
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from logging import Logger
from typing import cast

from faststream import ContextRepo, FastStream
from logging518 import config

from common.utils.nats.resource_manager import ResourceLockManager
from crawler.brokers import broker
from crawler.database.pg.db import async_session
from crawler.database.pg.schemas.telegram.sessions import Sessions
from crawler.routes import manage_resource, new_channel, schedule
from crawler.settings import settings

sys.excepthook = sys.__excepthook__
logger: Logger = logging.getLogger(__name__)


async def auto_refresher(context: ContextRepo) -> None:
    logger.info("auto refresher: Start.")
    while rlm := cast(ResourceLockManager | None, context.get("rlm", None)):
        if rlm:
            logger.info("auto refresher: Refreshing.")
            await rlm.refresh()
        await asyncio.sleep(settings.NATS_KV_TTL // 2)


@asynccontextmanager
async def lifespan(context: ContextRepo) -> AsyncIterator[None]:
    """Application lifecycle manager.

    Sets up resources and manages their lifecycle during application runtime.

    Args:
        context: Repository for sharing context across the application

    Yields:
        Control back to the application server
    """
    async with async_session() as session:
        resource_ids = await Sessions.get_all_id(session=session)
    await broker.start()
    async with ResourceLockManager(
        broker=broker,
        key_prefix=settings.NATS_PREFIX,
        resource_ids=resource_ids,
        kv_bucket=settings.NATS_KV_BUCKET,
        instance_id=settings.POD_NAME,
        ttl=settings.NATS_KV_TTL,
    ) as rlm:
        context.set_global("rlm", rlm)
        refresh_task = asyncio.create_task(auto_refresher(context))
        refresh_task.add_done_callback(
            lambda x: context.reset_global("auto_refresher")
        )
        context.set_global("auto_refresher", refresh_task)
        yield
        context.reset_global("rlm")


def create_app() -> FastStream:
    """Create and configure the FastStream application.

    Returns:
        Configured FastStream application instance
    """
    config.fileConfig("pyproject.toml")
    application = FastStream(
        broker=broker,
        title=settings.APP_NAME.title().replace("-", " "),
        logger=logger,
        version="1.0.0",
        lifespan=lifespan,
    )

    broker.include_router(new_channel.router)
    broker.include_router(schedule.router)
    broker.include_router(manage_resource.router)

    return application
