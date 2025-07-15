import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crawler.database.pg.schemas.telegram.mapping import (
    TelegramSessionEntityMap,
)
from crawler.database.pg.schemas.telegram.sessions import TelegramSession

logger = logging.getLogger(__name__)


async def find_subscribed_session(
    session: AsyncSession, entity_id: int
) -> TelegramSession | None:
    """
    Найти сессию Telegram, которая уже подписана на указанный канал
    """
    # Ищем сессию, которая уже связана с этой сущностью
    stmt = (
        select(TelegramSession)
        .join(
            TelegramSessionEntityMap,
            TelegramSessionEntityMap.session_id == TelegramSession.id,
        )
        .where(TelegramSessionEntityMap.entity_id == entity_id)
    )

    result = await session.execute(stmt)
    return result.scalars().first()


async def map_session_to_entity(
    session: AsyncSession, session_id: int, entity_id: int
) -> None:
    """
    Связывает сессию Telegram с сущностью (каналом), отмечая,
    что этот аккаунт уже подписан
    """
    # Проверяем существование записи
    stmt = select(TelegramSessionEntityMap).where(
        (TelegramSessionEntityMap.session_id == session_id)
        & (TelegramSessionEntityMap.entity_id == entity_id)
    )
    result = await session.execute(stmt)
    mapping = result.scalars().first()

    # Если связи нет, создаем ее
    if not mapping:
        mapping = TelegramSessionEntityMap(
            session_id=session_id, entity_id=entity_id
        )
        session.add(mapping)
        await session.flush()
        logger.info(
            "Создана связь сессии %s с каналом %s", session_id, entity_id
        )
