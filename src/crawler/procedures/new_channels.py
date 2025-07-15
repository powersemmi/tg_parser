import logging
from typing import NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession
from telethon.hints import Entity
from telethon.tl.types import Channel, Chat, User

from common.utils.nats.resource_manager import ResourceLockManager
from crawler.database.pg.queries.session_entity import (
    find_subscribed_session,
)
from crawler.database.pg.schemas import TelegramEntity, TelegramSession
from crawler.database.tg import ConnectManager

logger = logging.getLogger(__name__)


class SessionResult(NamedTuple):
    """Result of session preparation."""

    db_entity: TelegramEntity | None
    connect_manager: ConnectManager | None
    db_session: TelegramSession | None
    tg_entity: Entity


async def _prepare_new_channel_session(
    session: AsyncSession,
    rlm: ResourceLockManager,
    channel_url: str,
) -> SessionResult:
    """Prepare session for new channel or channel without subscribed session."""
    # Получаем сессию из общего пула
    db_session_id = await rlm.session().__aenter__()
    db_session = await TelegramSession.get(session=session, id=db_session_id)
    if db_session is None:
        await rlm.update_resources(
            await TelegramSession.get_all_id(session=session)
        )
        logger.warning(
            "Session %s not found, update local sessions",
            db_session_id,
        )
        raise ValueError(f"Session {db_session_id} not found")

    # Создаем ConnectManager
    connect_manager = ConnectManager(
        session=db_session.session,
        api_id=db_session.api_id,
        api_hash=db_session.api_hash,
        proxy=db_session.proxy,
    )
    await connect_manager.open()

    async with connect_manager.get_client() as client:
        # Получаем информацию о канале из Telegram
        tg_entity = await client.get_entity(channel_url)

    # В зависимости от типа сущности, получаем ID и имя
    if isinstance(tg_entity, Channel | Chat):
        entity_id = tg_entity.id
        entity_name = tg_entity.title
    elif isinstance(tg_entity, User):
        entity_id = tg_entity.id
        entity_name = tg_entity.username
    else:
        raise ValueError(f"Неизвестный тип сущности: {type(tg_entity)}")

    db_entity = await TelegramEntity.create_entity(
        session=session,
        channel_url=channel_url,
        entity_id=entity_id,
        entity_name=entity_name,
    )
    await session.commit()

    return SessionResult(db_entity, connect_manager, db_session, tg_entity)


async def _prepare_subscribed_session(
    db_entity: TelegramEntity,
    db_session: TelegramSession,
    rlm: ResourceLockManager,
) -> SessionResult:
    """Prepare session for channel with existing subscribed session."""
    # Используем подписанную сессию
    if db_session and await rlm.lock(db_session.id):
        logger.info(
            "Successfully acquired session %s "
            "already subscribed to channel %s",
            db_session.id,
            db_entity.entity_url,
        )

        connect_manager = ConnectManager(
            session=db_session.session,
            api_id=db_session.api_id,
            api_hash=db_session.api_hash,
            proxy=db_session.proxy,
        )
        await connect_manager.open()
        channel_id = int(f"-100{db_entity.entity_id}")
        async with connect_manager.get_client() as client:
            tg_entity = await client.get_input_entity(channel_id)

        return SessionResult(db_entity, connect_manager, db_session, tg_entity)
    else:
        raise ValueError("Failed to lock subscribed session")


async def prepare_channel_and_session(
    session: AsyncSession,
    rlm: ResourceLockManager,
    channel_url: str,
    entity_id: int | None = None,
) -> SessionResult:
    """Prepare channel entity and session for data collection.

    Args:
        session: Database session
        rlm: Resource lock manager
        channel_url: URL of the Telegram channel
        entity_id: Optional entity ID if channel exists

    Returns:
        Tuple of (entity, connect_manager, db_session, rlm_locked):
        - entity: TelegramEntity object
        - connect_manager: ConnectManager for Telegram API
        - db_session: TelegramSession object
        - tg_entity: Telegram entity object from Telegram API
    """

    db_session = None

    # Находим сущность по channel_url
    if entity_id:
        db_entity = await TelegramEntity.get_by_entity_id(session, entity_id)
    else:
        db_entity = await TelegramEntity.get_by_url(session, channel_url)

    # Находим подписанную сессию для существующей сущности
    if db_entity:
        db_session = await find_subscribed_session(session, db_entity.id)

    return (
        await _prepare_new_channel_session(
            session=session,
            rlm=rlm,
            channel_url=channel_url,
        )
        if db_entity is None or db_session is None
        else await _prepare_subscribed_session(
            db_entity=db_entity,
            db_session=db_session,
            rlm=rlm,
        )
    )
