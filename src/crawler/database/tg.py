"""Telegram client connection module.

Provides utilities for connecting to the Telegram API with session management.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from logging import Logger
from typing import Annotated, Any, Self, TypedDict, Unpack, cast

from fast_depends import Depends
from faststream import Context
from pydantic import BaseModel, Field, ValidationError
from pydantic.networks import AnyUrl
from python_socks import ProxyType
from sqlalchemy.ext.asyncio import AsyncSession
from telethon import TelegramClient
from telethon.sessions import StringSession
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from common.utils.nats.resource_manager import ResourceLockManager
from crawler.database.pg.db import get_session
from crawler.database.pg.schemas.telegram.sessions import TelegramSession

logger: Logger = logging.getLogger(__name__)


class ProxySettings(BaseModel):
    """Proxy settings model for Telegram client connections.

    Supports various proxy schemes (socks4, socks5, http, https).
    """

    url: Annotated[
        AnyUrl,
        Field(..., description="Proxy URL, e.g. socks5://user:pass@host:port"),
    ]

    def to_telethon_proxy(
        self,
    ) -> tuple[ProxyType, str, int, bool, str | None, str | None]:
        """Convert URL to tuple format for Telethon/python-socks.

        Transforms the proxy URL into the format expected by Telethon:
        (proxy_type, host, port, rdns, username, password)

        Returns:
            Tuple containing proxy configuration parameters

        Raises:
            ValueError: If proxy scheme is not supported
        """
        scheme = self.url.scheme.lower()
        host = cast(str, self.url.host)
        port = cast(int, self.url.port)
        username = self.url.username or None
        password = self.url.password or None
        rdns = True  # Remote DNS resolution by default

        # Using match-case from Python 3.13 for ProxyType selection
        match scheme:
            case "socks5" | "socks5h":
                proxy_type = ProxyType.SOCKS5
            case "socks4" | "socks4a":
                proxy_type = ProxyType.SOCKS4
            case "http" | "https":
                proxy_type = ProxyType.HTTP
            case _:
                raise ValueError(f"Unsupported proxy scheme: {scheme!r}")

        return proxy_type, host, port, rdns, username, password


class ClientConfigType(TypedDict):
    """Type definition for client configuration parameters.

    Used for type checking when passing configuration parameters.
    """

    session: str
    api_id: int
    api_hash: str
    proxy: str


@dataclass
class ClientConfig:
    """Configuration dataclass for Telegram client.

    Stores all necessary parameters for establishing a Telegram connection.
    """

    session: str
    api_id: int
    api_hash: str
    proxy: str | None = None


class ConnectManager:
    """Manager for Telegram client connections.

    Handles connection lifecycle, retries, and exclusive access to the client.
    """

    def __init__(self, **kwargs: Unpack[ClientConfigType]) -> None:
        """Initialize connection manager with client configuration.

        Args:
            **kwargs: Client configuration parameters
        """
        self._lock = asyncio.Lock()
        self._config: ClientConfig = ClientConfig(**kwargs)
        self._client: TelegramClient = self._create_client()

    def _create_client(self) -> TelegramClient:
        """Instantiate a new TelegramClient with current configuration.

        Returns:
            Configured TelegramClient instance

        Raises:
            ValueError: If proxy URL is invalid
        """
        session = StringSession(self._config.session)
        proxy_args = None
        if self._config.proxy:
            try:
                ps = ProxySettings(url=self._config.proxy)
                proxy_args = ps.to_telethon_proxy()
                logger.info("Proxy configured: %s", proxy_args[:3])
            except ValidationError as e:
                logger.error("Invalid proxy URL: %s", e)
                raise ValueError(f"Invalid proxy URL: {e}") from e

        return TelegramClient(
            session,
            self._config.api_id,
            self._config.api_hash,
            proxy=proxy_args,
        )

    async def open(self) -> None:
        """Connect the client with retries on network errors.

        Uses tenacity to retry up to 3 times with exponential backoff.
        """
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        ):
            with attempt:
                if not self._client.is_connected():
                    logger.info("Connecting to Telegram...")
                    await self._client.connect()
                    logger.info("Connected.")

    async def close(self) -> None:
        """Disconnect the client if connected."""
        if self._client.is_connected():
            logger.info("Disconnecting from Telegram...")
            await self._client.disconnect()
            logger.info("Disconnected.")

    async def __aenter__(self) -> Self:
        """Async context manager entry.

        Returns:
            Self reference to the manager
        """
        await self.open()
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Async context manager exit.

        Ensures client is properly disconnected.
        """
        await self.close()

    @asynccontextmanager
    async def get_client(self) -> AsyncIterator[TelegramClient]:
        """Async-context for exclusive client access.

        Usage:
            async with manager.get_client() as client:
                # client is your TelegramClient instance

        Yields:
            Active TelegramClient instance

        Raises:
            ValueError: If client is not available
        """
        async with self._lock:
            if self._client is None:
                raise ValueError("TgClient is not open")
            yield self._client

    async def update_credentials(
        self, **kwargs: Unpack[ClientConfigType]
    ) -> None:
        """Atomically update client credentials and recreate client instance.

        Blocks access from other coroutines until completion.

        Args:
            **kwargs: New credential parameters to update
        """
        async with self._lock:
            await self.close()
            self._config = ClientConfig(**{
                **asdict(self._config),
                **kwargs,
            })
            self._client = self._create_client()
            logger.info("Credentials updated successfully.")


async def get_tg_client(
    session: Annotated[AsyncSession, Depends(get_session, use_cache=False)],
    rlm: Annotated[ResourceLockManager, Depends(Context())],
) -> AsyncIterator[ConnectManager]:
    """Get a Telegram client connection manager.

    Retrieves session information from the database and creates a connection.

    Args:
        session: Database session
        rlm: Resource lock manager for managing Telegram session access

    Yields:
        Telegram connection manager

    Raises:
        ValueError: If the session ID is not found in the database
    """
    async with rlm.session() as tg_session_id:
        tg_session = await TelegramSession.get(
            session=session, id=tg_session_id
        )
        if tg_session:
            async with ConnectManager(
                session=tg_session.session,
                api_id=int(tg_session.api_id),
                api_hash=tg_session.api_hash,
                proxy=tg_session.proxy,
            ) as cm:
                yield cm
                return

        # Only reach here if tg_session is None
        raise ValueError(f"{tg_session_id=} not in sessions table")
