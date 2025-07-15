"""Telegram message parsing module.

Provides utilities for crawling and processing messages from Telegram channels.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from logging import Logger
from typing import Any

import asyncstdlib
from sqlalchemy.ext.asyncio import AsyncSession
from telethon.errors import FloodWaitError

from crawler.database.pg.queries.session_entity import map_session_to_entity
from crawler.database.pg.schemas.telegram.entities import TelegramEntity
from crawler.database.tg import ConnectManager

logger: Logger = logging.getLogger(__name__)


@dataclass
class TelegramMessage:
    """Message data from Telegram channel.

    Represents structured message content retrieved from Telegram.
    """

    entity_id: int
    message_id: int
    date: str
    text: str
    raw: str

    @classmethod
    def from_telethon_message(
        cls, entity_id: int, message: Any
    ) -> "TelegramMessage":
        """Create object from a Telethon message.

        Args:
            entity_id: Channel entity identifier
            message: Telethon message object from telethon.tl.types.Message

        Returns:
            New TelegramMessage instance
        """
        # Извлекаем текст сообщения из поля message
        message_text = ""
        if hasattr(message, "message") and message.message is not None:
            message_text = message.message

        # Извлекаем дату сообщения
        message_date = getattr(message, "date", None)
        date_str = message_date.isoformat() if message_date else None

        # Получаем ID сообщения
        message_id = getattr(message, "id", 0)

        return cls(
            entity_id=entity_id,
            message_id=message_id,
            date=date_str,
            text=message_text,
            raw=message.to_json(),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for compatibility.

        Returns:
            Dictionary representation of the message
        """
        return {
            "entity_id": self.entity_id,
            "message_id": self.message_id,
            "date": self.date,
            "text": self.text,
            "raw": self.raw,
        }

    @classmethod
    def create_info_message(
        cls,
        message_type: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create an informational message.

        Args:
            message_type: Type of message (info, error, success)
            message: Message text content
            data: Optional additional data

        Returns:
            Dictionary with message information
        """
        result = {"type": message_type, "message": message}
        if data:
            result.update(data)
        return result


@dataclass
class TelegramMessageMetadata:
    """Metadata for collecting statistics of Telegram channel messages.

    Tracks message IDs, timestamps and count of processed messages.
    """

    from_message_id: int | None = None
    to_message_id: int | None = None
    from_datetime: datetime | None = None
    to_datetime: datetime | None = None
    count: int = 0

    def update_message(self, message_id: int, message_date: datetime) -> None:
        """Update metadata with information about a new message.

        Args:
            message_id: ID of the processed message
            message_date: Datetime of the processed message
        """
        if self.from_message_id is None:
            self.from_message_id = message_id
            self.from_datetime = message_date

        self.to_message_id = message_id
        self.to_datetime = message_date
        self.count += 1

    def get_stats(
        self,
    ) -> tuple[int | None, int | None, datetime | None, datetime | None, int]:
        """Get statistics as a tuple.

        Returns:
            Tuple containing (from_message_id, to_message_id, from_datetime,
            to_datetime, count)
        """
        return (
            self.from_message_id,
            self.to_message_id,
            self.from_datetime,
            self.to_datetime,
            self.count,
        )


async def _get_telegram_entity(client: Any, entity: TelegramEntity) -> Any:
    """Get Telegram entity by ID or URL.

    Args:
        client: Telegram client instance
        entity: Entity database record

    Returns:
        Telethon entity object
    """
    channel_id = int(f"-100{entity.entity_id}")
    try:
        # Try to get by ID (faster)
        return await client.get_input_entity(channel_id)
    except ValueError:
        # If failed, get by URL
        return await client.get_entity(entity.entity_url)


def _process_message(
    message: Any,
    entity_id: int,
    from_datetime: datetime,
    metadata: TelegramMessageMetadata,
) -> tuple[TelegramMessage | None, bool]:
    """Process message and update metadata.

    Args:
        message: Telethon message object
        entity_id: ID of the channel entity
        from_datetime: Starting datetime for collection
        metadata: Metadata object to update

    Returns:
        Tuple of (message object, processed flag)
    """
    if message.date >= from_datetime:
        # Update metadata
        metadata.update_message(message.id, message.date)

        # Create message object
        message_obj = TelegramMessage.from_telethon_message(entity_id, message)
        return message_obj, True
    return None, False


def _handle_flood_wait_error(
    e: FloodWaitError,
    metadata: TelegramMessageMetadata,
    entity: TelegramEntity,
) -> bool:
    """Handle FloodWaitError from Telegram API.

    Args:
        e: FloodWaitError exception
        metadata: Collection metadata
        entity: Channel entity

    Returns:
        True if partial data was collected, False otherwise
    """
    logger.warning(
        "FloodWaitError: need to wait %s seconds for channel %s",
        e.seconds,
        entity.entity_url,
    )
    # Save what we've collected so far
    if metadata.count > 0:
        logger.info(
            "Collected %s messages before FloodWaitError",
            metadata.count,
        )
        return True
    return False


async def _iterate_messages(
    client: Any,
    tg_entity: Any,
    entity_id: int,
    entity: TelegramEntity,
    from_datetime: datetime,
    metadata: TelegramMessageMetadata,
) -> AsyncIterator[tuple[TelegramMessage | None, TelegramMessageMetadata]]:
    """Iterate through channel messages and process them.

    Args:
        client: Telegram client instance
        tg_entity: Telethon entity object
        entity_id: ID of the channel entity
        entity: Channel entity database record
        from_datetime: Starting datetime for collection
        metadata: Metadata object to update

    Yields:
        Tuple of (message object, metadata)

    Raises:
        ValueError: If no messages are found in the specified timeframe
    """
    # Iterate through messages
    async for _counter, message in asyncstdlib.enumerate(
        client.iter_messages(entity=tg_entity, reverse=False)
    ):
        message_obj, processed = _process_message(
            message, entity_id, from_datetime, metadata
        )

        if not processed:
            # If message is older than the specified date, stop collection
            break

        # Return message and metadata
        yield message_obj, metadata

        # Log every 100 messages
        if metadata.count % 100 == 0:
            logger.info(
                "Collected %s messages from channel %s (%s)",
                metadata.count,
                entity.entity_name,
                entity.entity_url,
            )

        # Let other tasks work
        if metadata.count % 20 == 0:
            await asyncio.sleep(0)

    # Check for no messages
    if metadata.count == 0:
        raise ValueError(
            f"Could not find messages in channel {entity.entity_url} "
            f"from {from_datetime}"
        )

    logger.info(
        "Completed collection from channel %s (%s): collected %s messages",
        entity.entity_name,
        entity.entity_url,
        metadata.count,
    )


async def crawl_messages(
    tg_session_id: int,
    entity_id: int,
    from_datetime: datetime,
    db_session: AsyncSession,
    connect_manager: ConnectManager,
) -> AsyncIterator[tuple[TelegramMessage | None, TelegramMessageMetadata]]:
    """Asynchronous iterator for collecting messages from a Telegram channel.

    Args:
        tg_session_id: ID of the Telegram session
        entity_id: ID of the channel entity
        from_datetime: Starting datetime for collection
        db_session: Database session
        connect_manager: Telegram connection manager

    Yields:
        Tuple of (message object, metadata)

    Raises:
        ValueError: If channel is not found
        Exception: For any other errors during collection
    """
    # Get channel entity
    entity = await TelegramEntity.get(db_session, entity_id)
    if not entity:
        raise ValueError(f"Channel with ID {entity_id} not found")

    # Initialize metadata
    metadata = TelegramMessageMetadata()

    # Use Telegram client
    async with connect_manager.get_client() as client:
        try:
            # Get Telegram entity
            tg_entity = await _get_telegram_entity(client, entity)

            # Update session-channel mapping
            await map_session_to_entity(db_session, tg_session_id, entity_id)

            # Iterate through messages and process them
            async for message_data in _iterate_messages(
                client, tg_entity, entity_id, entity, from_datetime, metadata
            ):
                yield message_data

        except FloodWaitError as e:
            # Handle rate limiting from Telegram
            if _handle_flood_wait_error(e, metadata, entity):
                # Return final metadata
                yield None, metadata
            else:
                raise
        except Exception as e:
            logger.exception(
                "Error collecting messages from channel %s: %s",
                entity.entity_url,
                e,
            )
            raise
