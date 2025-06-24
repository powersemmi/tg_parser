from unittest.mock import AsyncMock, MagicMock

import pytest
from faststream.nats import NatsBroker


@pytest.fixture
def broker_mock() -> tuple[MagicMock, MagicMock]:
    """
    Фикстура, возвращающая мок-брокер и мок-CLient KV.
    """
    broker = MagicMock(spec=NatsBroker)
    kv_client = MagicMock()
    # Настройка асинхронных методов KV
    kv_client.create = AsyncMock()
    kv_client.update = AsyncMock()
    kv_client.delete = AsyncMock()
    kv_client.purge = AsyncMock()
    kv_client.get = AsyncMock()
    kv_client.keys = AsyncMock()
    # broker.key_value возвращает kv_client
    broker.key_value = AsyncMock(return_value=kv_client)
    return broker, kv_client
