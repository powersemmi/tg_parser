import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from typing import Any, Self, TypedDict, Unpack, cast

from faststream.nats import NatsBroker
from pydantic import BaseModel, Field, ValidationError
from pydantic.networks import AnyUrl
from python_socks import ProxyType
from sqlalchemy.ext.asyncio import AsyncEngine
from telethon import TelegramClient
from telethon.sessions import StringSession
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


class ProxySettings(BaseModel):
    # Поддерживаем все URL‑прокси-схемы (socks4, socks5, http, https...)
    url: AnyUrl = Field(
        ..., description="Proxy URL, e.g. socks5://user:pass@host:port"
    )

    def to_telethon_proxy(
        self,
    ) -> tuple[ProxyType, str, int, bool, str | None, str | None]:
        """
        Преобразовать URL в кортеж для Telethon/python-socks:

            (proxy_type, host, port, rdns, username, password)
        """
        scheme = self.url.scheme.lower()
        host = cast(str, self.url.host)
        port = cast(int, self.url.port)
        username = self.url.username or None
        password = self.url.password or None
        rdns = True  # резолв DNS удалённо по умолчанию

        # Используем match-case из Python 3.13 для выбора ProxyType
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
    session: str
    api_id: int
    api_hash: str
    proxy: str


@dataclass
class ClientConfig:
    session: str
    api_id: int
    api_hash: str
    proxy: str | None = None


class ConnectManager:
    def __init__(
        self, engine: AsyncEngine, **kwargs: ClientConfigType
    ) -> None:
        self._lock = asyncio.Lock()
        self._client = None
        self._config = ClientConfig(**kwargs)
        self.db = engine

    def _create_client(self) -> TelegramClient:
        """
        Инстанцирует новый TelegramClient.
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
        """
        Connect the client, with retries on network errors.
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
        await self.open()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    @asynccontextmanager
    async def get_client(self) -> TelegramClient:
        """
        Async-context for exclusive client access.

        Usage:
            async with manager.get_client() as client:
                # client — ваш TelegramClient
        """
        async with self._lock:
            if self._client is None:
                raise ValueError("TgClient is not open")
            yield self._client

    async def update_credentials(
        self, **kwargs: Unpack[ClientConfigType]
    ) -> None:
        """
        Atomically update client credentials & recreate client instance.
        Блокирует доступ другим корутинам до завершения.
        """
        async with self._lock:
            await self.close()
            if self._config is None:
                self._config = ...
            else:
                self._config = ClientConfig(**{
                    **asdict(self._config),
                    **kwargs,
                })
            self._client = self._create_client()
            logger.info("Credentials updated successfully.")


class SessionManager:
    def __init__(self, broker: NatsBroker, key_prefix: str) -> None:
        self.cm: ConnectManager | None
        self.broker = broker
        self.key_prefix = key_prefix
        self._session_keys: list[int] | None = None

    async def open(self) -> None: ...

    async def exit(self) -> None: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(self, *args: Any) -> None: ...

    @asynccontextmanager
    async def _lock(self): ...

    @asynccontextmanager
    async def session(self) -> ConnectManager:
        async with self._lock():
            async with ConnectManager() as cm:
                self.cm = cm
                yield self.cm
