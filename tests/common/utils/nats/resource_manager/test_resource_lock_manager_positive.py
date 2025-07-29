from typing import Any
from unittest.mock import AsyncMock

from common.utils.nats.resource_manager import (
    ResourceLockManager,
    ResourceState,
)


async def test_lock_success(broker_mock: tuple[Any, Any]) -> None:
    broker, kv = broker_mock
    kv.create.return_value = 42

    manager = ResourceLockManager(
        broker=broker,
        key_prefix="prefix",
        resource_ids=[1],
        kv_bucket="bucket",
        instance_id="inst",
        ttl=10,
    )
    result = await manager.lock(1)
    assert result

    state = manager._states[1]
    assert state.locked
    assert state.version == 42
    kv.create.assert_awaited_once_with("prefix.1", b"inst")


async def test_unlock_and_cleanup(broker_mock: tuple[Any, Any]) -> None:
    broker, kv = broker_mock

    manager = ResourceLockManager(
        broker=broker,
        key_prefix="k",
        resource_ids=[3],
        kv_bucket="b",
        instance_id="id",
        ttl=5,
    )
    manager._states[3] = ResourceState(resource_id=3, version=10, locked=True)

    await manager.unlock(3)
    kv.purge.assert_awaited_once_with("k.3")

    state = manager._states[3]
    assert not state.locked
    assert state.version is None


async def test_refresh_success(broker_mock: tuple[Any, Any]) -> None:
    broker, kv = broker_mock

    manager = ResourceLockManager(
        broker=broker,
        key_prefix="pr",
        resource_ids=[4],
        kv_bucket="b",
        instance_id="iid",
        ttl=5,
    )
    manager._states[4] = ResourceState(resource_id=4, version=7, locked=True)
    manager._current = manager._states[4]
    kv.update.return_value = 8

    await manager.refresh()
    kv.update.assert_awaited_once_with("pr.4", b"iid", last=7)
    assert manager._current.version == 8


async def test_update_resources_add_and_remove(
    broker_mock: tuple[Any, Any],
) -> None:
    broker, _ = broker_mock

    manager = ResourceLockManager(
        broker=broker,
        key_prefix="k",
        resource_ids=[1, 2, 3],
        kv_bucket="b",
        instance_id="iid",
        ttl=5,
    )
    manager._states[2].locked = True

    await manager.update_resources([2, 4])
    assert 4 in manager._states
    assert 1 not in manager._states
    assert manager._states[2].locked


async def test_context_manager_enter_exit(
    broker_mock: tuple[Any, Any],
) -> None:
    broker, kv = broker_mock
    kv.create_entity = AsyncMock(side_effect=[100, 200])
    kv.delete = AsyncMock()

    manager = ResourceLockManager(
        broker=broker,
        key_prefix="cn",
        resource_ids=[6, 7],
        kv_bucket="b",
        instance_id="ident",
        ttl=5,
    )
    async with manager as m:
        await m._kv()
        assert m._kv_client is not None
        async with m.session(timeout=0.1) as rid:
            assert rid in {6, 7}

    # После выхода все ресурсы должны быть освобождены
    assert all(not st.locked for st in manager._states.values())
