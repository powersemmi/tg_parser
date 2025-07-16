from typing import Any

import pytest_mock
from nats.js.errors import KeyValueError, KeyWrongLastSequenceError

from common.utils.nats.resource_manager import (
    ResourceLockManager,
    ResourceState,
)


async def test_lock_failure_already_taken(
    broker_mock: tuple[Any, Any],
) -> None:
    broker, kv = broker_mock
    kv.create_entity.side_effect = KeyValueError(code=666)

    manager = ResourceLockManager(
        broker=broker,
        key_prefix="pfx",
        resource_ids=[2],
        kv_bucket="bucket",
        instance_id="id",
        ttl=5,
    )
    result = await manager.lock(2)
    assert not result

    state = manager._states[2]
    assert not state.locked
    assert state.version is None


async def test_refresh_sequence_error_triggers_reload(
    broker_mock: tuple[Any, Any], mocker: pytest_mock.MockFixture
) -> None:
    broker, kv = broker_mock

    manager = ResourceLockManager(
        broker=broker,
        key_prefix="x",
        resource_ids=[5],
        kv_bucket="b",
        instance_id="iid",
        ttl=5,
    )
    manager._states[5] = ResourceState(resource_id=5, version=1, locked=True)
    manager._current = manager._states[5]
    kv.update.side_effect = KeyWrongLastSequenceError()

    spy = mocker.spy(manager, "_reload_states")
    await manager.refresh()
    spy.assert_awaited()
