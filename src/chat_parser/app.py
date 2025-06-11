import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from faststream import ContextRepo, FastStream
from logging518 import config
from sqlalchemy import literal, select

from chat_parser.brokers import broker
from chat_parser.database.pg.db import engine
from chat_parser.database.tg import TelethonClientManager
from chat_parser.routes import messages
from chat_parser.settings import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(context: ContextRepo) -> AsyncGenerator[None]:
    async with engine.connect() as conn:
        stmt = select(literal(1), literal(2), literal(3))
        res = await conn.execute(stmt)
        api_hash, api_id, session = tuple(res.one())
        async with TelethonClientManager(
            api_hash=api_hash, api_id=api_id, session=session
        ) as tcm:
            context.set_global("tcm", tcm)
            yield


def create_app() -> FastStream:
    application = FastStream(
        broker=broker,
        title=settings.APP_NAME.title().replace("-", " "),
        logger=logger,
        version="1.0.0",
        lifespan=lifespan,
    )

    broker.include_router(messages.router)

    return application


config.fileConfig("pyproject.toml")
app = create_app()
