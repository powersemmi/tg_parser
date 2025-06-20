import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from faststream import ContextRepo, FastStream
from logging518 import config

from crawler.brokers import broker
from crawler.database.tg import SessionManager
from crawler.routes import new_channel, schedule
from crawler.settings import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(context: ContextRepo) -> AsyncGenerator[None]:
    context.set_global("tcm", SessionManager())
    yield


def create_app() -> FastStream:
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
app = create_app()
