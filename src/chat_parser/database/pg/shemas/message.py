import logging

from sqlalchemy import BigInteger, Column, Table, func
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.ext.asyncio import AsyncSession

from chat_parser.database.pg.db import engine
from chat_parser.database.pg.queries.tables import check_exists

from .base import Base, metadata

logger = logging.getLogger(__name__)


def _create_table(name: str) -> Table:
    return Table(
        name,
        metadata,
        Column("id", BigInteger, primary_key=True),
        Column("raw", JSONB),
        Column("date", TIMESTAMP(timezone=True)),
        Column("created_at", TIMESTAMP(timezone=True), default=func.now()),
    )


async def get_channel_table(
    session: AsyncSession, schema: str, name: str
) -> Table:
    if await check_exists(session=session, schema=schema, name=name):
        logger.info("Table is already exists")
        return Table(name, metadata, autoload_with=engine.engine)

    logger.info("Try create table with length %s and name %s", len(name), name)
    cls = type(
        name,
        (Base,),
        {"__tablename__": name, "__table__": _create_table(name)},
    )
    cls.metadata = cls.__table__.metadata  # type: ignore[attr-defined]
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await session.commit()
    return cls  # type: ignore[return-value]
