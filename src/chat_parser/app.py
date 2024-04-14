import logging

from faststream import FastStream
from logging518 import config

from chat_parser.brokers import broker
from chat_parser.database.db import engine
from chat_parser.routes import parser
from chat_parser.settings import settings

logger = logging.getLogger(__name__)


async def on_startup() -> None:
    await (await engine.connect()).aclose()


async def on_shutdown() -> None:
    await engine.dispose()


def create_app() -> FastStream:
    application = FastStream(
        broker=broker,
        title=settings.APP_NAME.title().replace("-", " "),
        logger=logger,
        version="1.0.0",
    )
    application.on_startup(on_startup)
    application.on_shutdown(on_shutdown)

    broker.include_router(parser.router)

    return application


config.fileConfig("pyproject.toml")
app = create_app()
