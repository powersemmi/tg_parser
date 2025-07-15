"""Business logic for handling scheduled parsing tasks.

Contains functions for processing scheduled message collection.
"""

import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypedDict

from telethon.errors import FloodWaitError
from telethon.hints import Entity
from telethon.tl import TLObject
from telethon.tl.types import (
    Message,
    ReactionCustomEmoji,
    ReactionEmoji,
    ReactionEmpty,
    ReactionPaid,
)

from crawler.database.tg import ConnectManager

logger = logging.getLogger(__name__)

ReactionType: type = type[
    ReactionEmoji | ReactionCustomEmoji | ReactionPaid | ReactionEmpty
]


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


class ReactionDict(TypedDict):
    """Словарь для представления реакции на сообщение."""

    emoji: str  # Эмодзи или ID кастомной реакции
    count: int  # Количество реакций данного типа


class MessageDict(TypedDict):
    """Словарь для представления сообщения из Telegram.

    Используется для внутренней обработки сообщений в procedures.
    Структура соответствует MessageResponseModel и отражает основные поля
    из telethon.tl.types.Message:

    - id (int) -> message_id: ID сообщения
    - date (datetime): дата отправки
    - message/text (str) -> message: текст сообщения
    - from_id (PeerUser) -> sender_id: отправитель
    - peer_id (Peer) -> entity_id: ID чата/канала
    - reply_to (MessageReplyHeader) -> reply_to_message_id:
    ссылка на сообщение-ответ
    - replies (MessageReplies): информация о ответах на сообщение
    - views (int): количество просмотров
    - forwards (int): количество пересылок
    - media (MessageMedia): медиа-контент в сообщении
    - reactions (MessageReactions): реакции на сообщение
    """

    message_id: int
    entity_id: int
    entity_name: str
    sender_id: int | None
    sender_name: str | None
    date: datetime
    message: str  # Текст сообщения (из message или text поля)
    reactions: list[ReactionDict]  # Список реакций с emoji и count
    views: int | None
    forwards: int | None
    replies: int | None
    media_type: str | None
    media_url: str | None
    reply_to_message_id: int | None
    metadata: dict[str, Any]  # Дополнительные данные (entities и т.д.)


async def _iter_messages_locked(
    connect_manager: ConnectManager, entity: Entity
) -> AsyncIterator[Message]:
    """Iterate over messages for a given entity."""
    async with connect_manager.get_client() as client:
        async for message in client.iter_messages(
            entity=entity, reverse=False
        ):
            yield message


def _handle_reaction(reaction: ReactionType) -> str:
    match reaction:
        case ReactionEmoji():
            return reaction.emoticon
        case ReactionCustomEmoji():
            return str(reaction.document_id)
        case ReactionPaid():
            return "PAID STAR"
        case _:
            return "UNKNOWN"


def _handle_flood_wait_error(
    e: FloodWaitError,
    metadata: TelegramMessageMetadata,
    entity: Entity,
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
        entity.username,
    )
    # Save what we've collected so far
    if metadata.count > 0:
        logger.info(
            "Collected %s messages before FloodWaitError",
            metadata.count,
        )
        return True
    return False


def extract_telethon_message_data(
    message: Message, entity: Entity
) -> MessageDict:
    """Извлекает данные из объекта Message библиотеки Telethon.

    Обрабатывает все поля из telethon.tl.types.Message и преобразует их
    в формат MessageDict для дальнейшей обработки.

    Args:
        message: Объект сообщения Telethon
        entity: Сущность Telegram (канал, чат, пользователь)

    Returns:
        Кортеж из MessageDict и метаданных
    """
    # Извлекаем данные отправителя
    sender_id = None
    if hasattr(message, "from_id") and message.from_id:
        sender_id = getattr(message.from_id, "user_id", None)

    # Получаем имя отправителя
    sender_name = None
    if hasattr(message, "sender") and message.sender:
        if hasattr(message.sender, "first_name"):
            first_name = getattr(message.sender, "first_name", "")
            last_name = getattr(message.sender, "last_name", "")
            sender_name = f"{first_name} {last_name}".strip()
        elif hasattr(message.sender, "title"):
            sender_name = getattr(message.sender, "title", None)

    # Получаем текст сообщения
    message_text = ""
    if hasattr(message, "message"):
        message_text = message.message or ""

    # Получаем реакции
    reactions_list = []
    if hasattr(message, "reactions") and message.reactions:
        if hasattr(message.reactions, "results"):
            reactions_list = [
                {
                    "emoji": _handle_reaction(rc.reaction),
                    "count": rc.count,
                }
                for rc in message.reactions.results
            ]

    # Получаем данные о медиа-контенте
    media_type = None
    media_url = None
    if hasattr(message, "media") and message.media:
        media_type = message.media.__class__.__name__
        # URL медиа можно было бы извлечь, но требует дополнительной обработки

    # Получаем ID сообщения, на которое отвечают
    reply_to_msg_id = None
    if hasattr(message, "reply_to") and message.reply_to:
        reply_to_msg_id = getattr(message.reply_to, "reply_to_msg_id", None)

    # Получаем дополнительные метаданные
    metadata_dict = {}
    if hasattr(message, "entities") and message.entities:
        metadata_dict["entities"] = [
            {
                "type": e.__class__.__name__,
                "offset": e.offset,
                "length": e.length,
            }
            for e in message.entities
        ]

    # Формируем словарь сообщения
    return MessageDict(
        message_id=message.id,
        entity_id=entity.id,
        entity_name=entity.username,
        sender_id=sender_id,
        sender_name=sender_name,
        date=message.date,
        message=message_text,
        reactions=reactions_list,
        views=message.views,
        forwards=message.forwards,
        replies=message.replies.replies
        if isinstance(message.replies, TLObject)
        else None,
        media_type=media_type,
        media_url=media_url,
        reply_to_message_id=reply_to_msg_id,
        metadata=metadata_dict,
    )


async def collect_messages(
    entity: Entity,
    connect_manager: ConnectManager,
    condition: Callable[[Message], bool],
) -> AsyncIterator[tuple[MessageDict | None, TelegramMessageMetadata | None]]:
    """Collect messages from Telegram entity using connected client.

    Args:
        entity: Entity to collect messages from
        connect_manager: Connected Telegram client
        condition: Condition to filter messages by (e.g. by sender)

    Returns:
        Tuple of (collected_messages, metadata)
    """
    metadata: TelegramMessageMetadata | None = None
    # Обрабатываем полученные сообщения
    try:
        async for message in _iter_messages_locked(
            connect_manager=connect_manager, entity=entity
        ):
            if condition(message):
                break

            # Обновляем метаданные
            if metadata is None:
                metadata = TelegramMessageMetadata()
            if metadata is not None:
                metadata.update_message(message.id, message.date)

            yield extract_telethon_message_data(message, entity), metadata
    except FloodWaitError as e:
        # Handle rate limiting from Telegram
        if metadata is not None and _handle_flood_wait_error(
            e, metadata, entity
        ):
            # Return final metadata
            yield None, metadata
        else:
            yield None, None
