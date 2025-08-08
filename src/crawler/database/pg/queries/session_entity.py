import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crawler.database.pg.schemas.telegram.session_entity_map import (
    SessionEntityMap,
)
from crawler.database.pg.schemas.telegram.sessions import Sessions

logger = logging.getLogger(__name__)


async def find_subscribed_session(
    session: AsyncSession, entity_id: int
) -> Sessions | None:
    """
    Найти сессию Telegram, которая уже подписана на указанный канал.

    Выполняет SQL-запрос с JOIN для поиска сессии, связанной с указанной
    сущностью через таблицу связей TelegramSessionEntityMap.

    Args:
        session: Сессия SQLAlchemy
        entity_id: ID сущности канала

    Returns:
        Объект TelegramSession, если найдена подписанная сессия, иначе None
    """
    # Ищем сессию, которая уже связана с этой сущностью
    stmt = (
        select(Sessions)
        .join(
            SessionEntityMap,
            SessionEntityMap.session_id == Sessions.id,
        )
        .where(SessionEntityMap.entity_id == entity_id)
    )

    result = await session.execute(stmt)
    return result.scalars().first()


async def map_session_to_entity(
    session: AsyncSession, session_id: int, entity_id: int
) -> None:
    """
    Связывает сессию Telegram с сущностью (каналом), отмечая,
    что этот аккаунт уже подписан.

    Сначала проверяет существование записи в таблице связей,
    и если связи нет, создаёт её. Предотвращает дублирование связей
    благодаря проверке перед созданием.

    Args:
        session: Сессия SQLAlchemy
        session_id: ID сессии Telegram
        entity_id: ID сущности канала
    """
    # Проверяем существование записи
    stmt = select(SessionEntityMap).where(
        (SessionEntityMap.session_id == session_id)
        & (SessionEntityMap.entity_id == entity_id)
    )
    result = await session.execute(stmt)
    mapping = result.scalars().first()

    # Если связи нет, создаем ее
    if not mapping:
        mapping = SessionEntityMap(session_id=session_id, entity_id=entity_id)
        session.add(mapping)
        await session.flush()
        logger.info(
            "Создана связь сессии %s с каналом %s", session_id, entity_id
        )
