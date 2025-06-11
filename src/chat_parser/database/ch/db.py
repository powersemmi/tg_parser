from asyncio import Queue
from collections.abc import AsyncGenerator
from types import TracebackType
from typing import Any, Self
from urllib.parse import parse_qs, urlparse

import clickhouse_connect
from clickhouse_connect.driver import AsyncClient
from clickhouse_connect.driver.httputil import get_pool_manager

from chat_parser.settings import settings


def _cast_value(value: str) -> bool | int | float | str:
    """
    Пытается привести строку к bool, int, float или вернуть как str.
    """
    val_lower = value.lower()
    if val_lower in ("true", "1"):
        return True
    if val_lower in ("false", "0"):
        return False
    if value.isdigit():
        return int(value)
    try:
        return float(value)
    except ValueError:
        return value


class _PoolConnection:
    """
    Вспомогательный контекстный менеджер для клиента из пула.
    """

    def __init__(self, pool: Queue[AsyncClient]) -> None:
        self._pool: Queue[AsyncClient] = pool
        self.client: AsyncClient | None = None

    async def __aenter__(
        self,
    ) -> AsyncClient:
        self.client = await self._pool.get()
        return self.client

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        # гарантированно возвращаем клиент в пул
        if self.client is not None:
            await self._pool.put(self.client)


class ClickhousePool:
    """
    Асинхронный пул клиентов clickhouse-connect.

    Пример:
        async with ClickhousePool(
            url="http://user:pass@localhost:8123/mydb?compression=True",
            pool_size=5,
        ) as pool:
            async with pool.acquire() as client:
                result = await client.query(
                    "SELECT COUNT() FROM system.tables",
                )
                print(result.result_rows)
    """

    def __init__(
        self,
        url: str,
        pool_size: int = 10,
        **client_kwargs: Any,
    ) -> None:
        parsed = urlparse(url)
        self._host: str = parsed.hostname or "localhost"
        self._port: int = parsed.port or 8123
        self._username: str = parsed.username or "default"
        self._password: str = parsed.password or ""
        self._database: str = parsed.path.lstrip("/") or "default"

        qs: dict[str, list[str]] = parse_qs(parsed.query)
        parsed_params: dict[str, Any] = {
            k: _cast_value(v[-1]) for k, v in qs.items()
        }
        self._client_kwargs: dict[str, Any] = {
            **parsed_params,
            **client_kwargs,
        }

        self.pool_size: int = pool_size
        self._pool: Queue[AsyncClient] | None = None
        self._clients: list[AsyncClient] = []

    async def open(self) -> None:
        """Инициализирует пул клиентов."""
        if self._pool is not None:
            return
        pool_mgr = get_pool_manager()
        self._pool = Queue(maxsize=self.pool_size)
        for _ in range(self.pool_size):
            client = await clickhouse_connect.get_async_client(
                host=self._host,
                port=self._port,
                username=self._username,
                password=self._password,
                database=self._database,
                pool_mgr=pool_mgr,
                **self._client_kwargs,
            )
            self._clients.append(client)
            await self._pool.put(client)

    async def close(self) -> None:
        """Закрывает все клиенты и очищает пул."""
        if self._pool is None:
            return
        for client in self._clients:
            await client.close()
        self._clients.clear()
        self._pool = None

    async def __aenter__(self) -> Self:
        await self.open()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    def acquire(self) -> _PoolConnection:
        """
        Возвращает контекстный менеджер для получения клиента из пула.
        """
        if self._pool is None:
            raise RuntimeError(
                "Pool is not open."
                "Use 'async with ClickhousePool(...)' or call .open() first."
            )
        return _PoolConnection(self._pool)


ch_pool = ClickhousePool(
    url=settings.CLICKHOUSE_URL.unicode_string(),
    pool_size=settings.CH_POOL_SIZE,
)


async def get_client() -> AsyncGenerator[AsyncClient]:
    async with ch_pool.acquire() as conn:
        yield conn
