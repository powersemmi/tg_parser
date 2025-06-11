import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, cast

from pydantic import BaseModel, Field, ValidationError
from pydantic.networks import AnyUrl
from python_socks import ProxyType
from telethon import TelegramClient
from telethon.sessions import StringSession
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# Настраиваем логирование
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter(
    "[%(asctime)s] %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"
)
handler.setFormatter(formatter)
logger.addHandler(handler)


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


@dataclass
class ClientConfig:
    session: str
    api_id: int
    api_hash: str
    proxy: str | None = None


class TelethonClientManager:
    __slots__ = ("_client", "_config", "_lock")

    def __init__(
        self,
        session: str,
        api_id: int,
        api_hash: str,
        proxy: str | None = None,
    ):
        """
        Инициализация TelethonClientManager.

        :param session: StringSession или путь к файлу сессии.
        :param api_id: Telegram API ID.
        :param api_hash: Telegram API Hash.
        :param proxy: URL прокси, если нужен.
        """
        self._config = ClientConfig(
            session=session, api_id=api_id, api_hash=api_hash, proxy=proxy
        )
        self._lock = asyncio.Lock()
        self._client = self._create_client()

    def _create_client(self) -> TelegramClient:
        """Инстанцирует новый TelegramClient по текущей конфигурации."""
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

    async def __aenter__(self) -> "TelethonClientManager":
        await self.open()
        return self

    async def __aexit__(self, *args: Any) -> bool | None:
        await self.close()
        return False  # не подавлять исключения

    @asynccontextmanager
    async def get_client(self) -> TelegramClient:
        """
        Async-context for exclusive client access.

        Usage:
            async with manager.get_client() as client:
                # client — ваш TelegramClient
        """
        async with self._lock:
            await self.open()
            try:
                yield self._client
            finally:
                # не закрываем клиент, чтобы переиспользовать соединение
                pass

    async def update_credentials(
        self,
        session: str | None = None,
        api_id: int | None = None,
        api_hash: str | None = None,
        proxy: str | None = None,
    ) -> None:
        """
        Atomically update client credentials & recreate client instance.
        Блокирует доступ другим корутинам до завершения.
        """
        async with self._lock:
            await self.close()
            if session is not None:
                self._config.session = session
            if api_id is not None:
                self._config.api_id = api_id
            if api_hash is not None:
                self._config.api_hash = api_hash
            if proxy is not None:
                self._config.proxy = proxy

            self._client = self._create_client()
            logger.info("Credentials updated successfully.")
