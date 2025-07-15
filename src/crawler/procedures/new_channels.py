"""Procedures for processing new Telegram channels.

Provides utilities for channel discovery, verification and message collection.
"""

import logging
from collections.abc import AsyncIterator
from datetime import datetime
from logging import Logger
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from common.utils.nats.resource_manager import ResourceLockManager
from crawler.database.pg.queries.session_entity import (
    find_subscribed_session,
)
from crawler.database.pg.schemas.telegram.collections import (
    TelegramChannelCollection,
)
from crawler.database.pg.schemas.telegram.entities import TelegramEntity
from crawler.database.tg import ConnectManager, get_tg_client
from crawler.procedures.parser import (
    TelegramMessage,
    TelegramMessageMetadata,
    crawl_messages,
)

logger: Logger = logging.getLogger(__name__)


async def get_session_for_channel(
    session: AsyncSession,
    rlm: ResourceLockManager,
    entity: TelegramEntity | None = None,
) -> tuple[ConnectManager | None, int | None]:
    """Get a session for working with a channel.

    If the channel exists, tries to find a session already subscribed to it.

    Args:
        session: Database session
        rlm: Resource lock manager
        entity: Channel entity (if exists)

    Returns:
        Tuple (connect_manager, session_id):
        - connect_manager: Telegram connection manager
        - session_id: Session ID
    """
    if entity:
        subscribed_session = await find_subscribed_session(session, entity.id)

        if subscribed_session and await rlm.lock(subscribed_session.id):
            logger.info(
                "Successfully acquired session %s "
                "already subscribed to channel %s",
                subscribed_session.id,
                entity.entity_url,
            )

            try:
                # Create ConnectManager manually
                tg_manager = ConnectManager(
                    session=subscribed_session.session,
                    api_id=subscribed_session.api_id,
                    api_hash=subscribed_session.api_hash,
                    proxy=subscribed_session.proxy,
                )
                await tg_manager.open()
                return tg_manager, subscribed_session.id
            except Exception as e:
                logger.error("Error creating ConnectManager: %s", e)
                # Make sure to unlock the session if we failed to create
                # the manager
                await rlm.unlock(subscribed_session.id)
                # Continue to try with the common pool

    # If no subscribed session or failed to acquire it,
    # use the common pool
    try:
        async with rlm.session() as tg_session_id:
            # Get ConnectManager through standard mechanism
            client_gen = get_tg_client(session, rlm)

            # Handle both cases: when client_gen is an async iterator
            # and when it's a ConnectManager directly (for testing)
            if hasattr(client_gen, "__aiter__"):
                # Use it as an async iterator
                async for cm in client_gen:
                    return cm, tg_session_id
            else:
                # For testing compatibility
                return client_gen, tg_session_id
    except Exception as e:
        logger.error("Error getting Telegram session: %s", e)

    return None, None


async def release_resources(
    rlm: ResourceLockManager,
    tg_manager: ConnectManager | None,
    tg_session_id: int | None,
) -> None:
    """Release resources: close Telegram connection and unlock session.

    Args:
        rlm: Resource lock manager
        tg_manager: Telegram connection manager
        tg_session_id: Telegram session ID
    """
    if tg_manager and tg_session_id:
        try:
            await tg_manager.close()
            if await rlm.lock(
                tg_session_id
            ):  # Check that we still have the session
                await rlm.unlock(tg_session_id)
        except Exception as e:
            logger.error("Error releasing resources: %s", e)


async def _save_collection_metadata(
    session: AsyncSession,
    entity: TelegramEntity,
    metadata: TelegramMessageMetadata,
) -> tuple[bool, dict[str, Any]]:
    """Save metadata about the collected messages.

    Args:
        session: Database session
        entity: Channel entity
        metadata: Collection metadata

    Returns:
        Tuple of (success, result_data)
    """
    if metadata and metadata.count > 0:
        stats = metadata.get_stats()
        from_msg_id = stats[0]  # from_msg_id
        to_msg_id = stats[1]  # to_msg_id
        from_dt = stats[2]  # from_dt
        to_dt = stats[3]  # to_dt
        count = stats[4]  # count

        # Check that all required fields are not None
        if (
            from_msg_id is not None
            and to_msg_id is not None
            and from_dt is not None
            and to_dt is not None
        ):
            await TelegramChannelCollection.create_collection_record(
                session=session,
                entity_id=entity.id,
                from_message_id=from_msg_id,
                to_message_id=to_msg_id,
                from_datetime=from_dt,
                to_datetime=to_dt,
                messages_count=count,
            )
            await session.commit()

            return True, {
                "message": f"Successfully collected {count} messages "
                f"from channel {entity.entity_url}",
                "data": {
                    "count": count,
                    "from": from_dt.isoformat() if from_dt else None,
                    "to": to_dt.isoformat() if to_dt else None,
                },
            }

    # If metadata is incorrect or no messages
    return False, {
        "message": f"No new messages found in channel {entity.entity_url}"
    }


async def _collect_messages(
    session: AsyncSession,
    entity: TelegramEntity,
    tg_session_id: int,
    tg_manager: ConnectManager,
    from_datetime: datetime,
) -> AsyncIterator[tuple[dict[str, Any], TelegramMessageMetadata | None]]:
    """Collect messages from a channel.

    Args:
        session: Database session
        entity: Channel entity
        tg_session_id: Telegram session ID
        tg_manager: Telegram connection manager
        from_datetime: Starting datetime for collection

    Yields:
        Tuple of (message_data, metadata)
    """
    metadata = None
    try:
        # Collect messages
        async for message_obj, msg_metadata in crawl_messages(
            tg_session_id=tg_session_id,
            entity_id=entity.id,
            from_datetime=from_datetime,
            db_session=session,
            connect_manager=tg_manager,
        ):
            metadata = msg_metadata
            if message_obj is None:
                # We might get None with FloodWaitError
                continue

            # Pass message and metadata forward
            yield message_obj.to_dict(), metadata

        # After collection is complete, save metadata
        if metadata is not None:
            success, result = await _save_collection_metadata(
                session=session, entity=entity, metadata=metadata
            )
        else:
            success, result = (
                False,
                {
                    "message": (
                        f"Failed to collect metadata for channel "
                        f"{entity.entity_url}"
                    )
                },
            )

        if success:
            yield (
                TelegramMessage.create_info_message(
                    "success", result["message"], result["data"]
                ),
                None,
            )
        else:
            yield (
                TelegramMessage.create_info_message("info", result["message"]),
                None,
            )

    except Exception as e:
        logger.exception("Error collecting messages: %s", e)
        await session.rollback()

        yield (
            TelegramMessage.create_info_message(
                "error", f"Error collecting messages: {e!s}"
            ),
            None,
        )


async def _prepare_channel(
    session: AsyncSession,
    rlm: ResourceLockManager,
    channel_url: str,
    from_datetime: datetime,
) -> tuple[
    TelegramEntity | None, ConnectManager | None, int | None, str | None
]:
    """Prepare channel for data collection: check existence,
    get session, create channel if necessary.

    Args:
        session: Database session
        rlm: Resource lock manager
        channel_url: URL of the Telegram channel
        from_datetime: Starting datetime for collection

    Returns:
        Tuple of (entity, manager, session_id, error_message)
    """
    # Check if channel exists in database
    entity = await TelegramEntity.get_by_url(session, channel_url)

    # If channel exists, check for overlap with already collected data
    if entity:
        has_overlap, message = await _check_data_overlap(
            session, entity, from_datetime
        )
        if has_overlap:
            return entity, None, None, message

    # Get session for working with the channel
    tg_manager, tg_session_id = await get_session_for_channel(
        session, rlm, entity
    )
    if not tg_manager:
        return (
            None,
            None,
            None,
            "Failed to get available Telegram session",
        )

    # If channel is new, create it
    if not entity:
        async with tg_manager.get_client() as client:
            entity, _ = await TelegramEntity.create_entity(
                session,
                channel_url,
                client,
            )
            await session.commit()

    return entity, tg_manager, tg_session_id, None


def _process_info_message(
    message_data: dict[str, Any], batch: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], bool, str]:
    """Process an information message and return batch and status.

    Args:
        message_data: Message data containing type and message content
        batch: Current batch of messages being processed

    Returns:
        Tuple containing the updated batch, success flag, and message text
    """
    message_type = message_data["type"]
    message_text = message_data["message"]

    success = message_type in ("success", "info")

    if message_type == "error":
        logger.error(message_text)
    else:
        logger.info(message_text)

    return batch, success, message_text


def _process_data_message(
    message_data: dict[str, Any],
    batch: list[dict[str, Any]],
    max_batch_size: int,
) -> tuple[list[dict[str, Any]], bool]:
    """Process a data message and return the result.

    Args:
        message_data: Message data to be processed
        batch: Current batch of messages
        max_batch_size: Maximum size of a batch

    Returns:
        Tuple containing the updated batch and a flag indicating if
        the batch is ready to send
    """
    batch.append(message_data)

    if len(batch) >= max_batch_size:
        return batch, True
    return batch, False


async def _process_channel_messages(
    session: AsyncSession,
    rlm: ResourceLockManager,
    channel_url: str,
    from_datetime: datetime,
    max_batch_size: int,
) -> tuple[list[list[dict[str, Any]]], bool, str]:
    """Process messages from a channel and form batches.

    Connects to a Telegram channel, retrieves messages since the given
    datetime, and organizes them into batches for processing. Handles both
    data messages (actual content) and info/status messages.

    Args:
        session: Database session for accessing storage
        rlm: Resource lock manager for Telegram API access coordination
        channel_url: URL of the Telegram channel to process
        from_datetime: Starting datetime for message collection
        max_batch_size: Maximum size of a message batch

    Returns:
        Tuple containing all batches, success flag, and final message
    """
    success: bool = False
    final_message: str = "Failed to process channel"
    batch: list[dict[str, Any]] = []
    all_batches: list[list[dict[str, Any]]] = []

    async for message_data, _metadata in process_channel(
        session=session,
        rlm=rlm,
        channel_url=str(channel_url),
        from_datetime=from_datetime,
    ):
        if "type" in message_data:
            if batch:
                all_batches.append(batch.copy())
                batch = []

            batch, msg_success, msg_text = _process_info_message(
                message_data, batch
            )
            success = msg_success
            final_message = msg_text
        else:
            batch, should_send = _process_data_message(
                message_data, batch, max_batch_size
            )
            if should_send:
                all_batches.append(batch.copy())
                batch = []

    if batch:
        all_batches.append(batch)

    return all_batches, success, final_message


async def process_channel(
    session: AsyncSession,
    rlm: ResourceLockManager,
    channel_url: str,
    from_datetime: datetime,
) -> AsyncIterator[tuple[dict[str, Any], TelegramMessageMetadata | None]]:
    """Process Telegram channel: check existence, prepare data collection.

    Args:
        session: Database session
        rlm: Resource lock manager
        channel_url: URL of the Telegram channel
        from_datetime: Starting datetime for collection

    Yields:
        Tuple of (message_data, metadata)
    """
    tg_manager = None
    tg_session_id = None

    try:
        # Prepare channel for data collection
        (
            entity,
            tg_manager,
            tg_session_id,
            error_message,
        ) = await _prepare_channel(session, rlm, channel_url, from_datetime)

        # Handle possible errors
        if error_message:
            # Use "error" type for session availability issues,
            # "info" for others
            message_type = (
                "error"
                if "Failed to get available Telegram session" in error_message
                else "info"
            )
            yield (
                TelegramMessage.create_info_message(
                    message_type, error_message
                ),
                None,
            )
            return

        if not entity or not tg_manager or not tg_session_id:
            yield (
                TelegramMessage.create_info_message(
                    "error", "Error preparing channel for data collection"
                ),
                None,
            )
            return

        # Collect messages from the channel
        async for result in _collect_messages(
            session, entity, tg_session_id, tg_manager, from_datetime
        ):
            yield result

    except Exception as e:
        logger.exception("Error preparing data collection: %s", e)
        yield (
            TelegramMessage.create_info_message(
                "error", f"Error preparing data collection: {e!s}"
            ),
            None,
        )

    finally:
        # Release resources
        if tg_manager and tg_session_id:
            await release_resources(rlm, tg_manager, tg_session_id)
