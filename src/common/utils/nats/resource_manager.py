import asyncio
import logging
import random
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Literal, Self, cast

from faststream.nats import NatsBroker
from nats.js.errors import KeyValueError, KeyWrongLastSequenceError
from nats.js.kv import KeyValue

logger = logging.getLogger(__name__)


@dataclass
class ResourceState:
    resource_id: int
    version: int | None = None
    locked: bool = False


class ResourceLockManager:
    """
    Управляет локальными копиями ключей ресурсов в NATS JetStream KV.
    Позволяет асинхронно захватывать и освобождать ресурсы между воркерами.
    """

    def __init__(
        self,
        broker: NatsBroker,
        key_prefix: str,
        resource_ids: list[int],
        kv_bucket: str,
        instance_id: str,
        ttl: int = 60,
    ):
        self.broker = broker
        self.key_prefix = key_prefix.rstrip(".") + "."
        self.kv_bucket = kv_bucket
        self.instance_id = instance_id
        self.ttl = ttl

        # состояние всех ресурсов
        self._states: dict[int, ResourceState] = {
            rid: ResourceState(resource_id=rid) for rid in resource_ids
        }
        self._current: ResourceState | None = None
        self._lock = asyncio.Lock()
        self._kv_client: KeyValue | None = None

    async def _kv(self) -> KeyValue:
        if self._kv_client is None:
            # создаём bucket KV с дефолтным ttl
            self._kv_client = await self.broker.key_value(
                bucket=self.kv_bucket, ttl=self.ttl, declare=True
            )
        return self._kv_client

    def _key_name(self, resource_id: int) -> str:
        return f"{self.key_prefix}{resource_id}"

    async def _reload_states(self) -> None:
        """
        Перезагрузить все локальные состояния из KV.
        """
        kv = await self._kv()
        try:
            keys = await kv.keys()
        except Exception as e:
            logger.warning(
                "Не удалось получить список ключей для перезагрузки: %s", e
            )
            return
        async with self._lock:
            # сбросим занятость всех
            for state in self._states.values():
                state.version = None
                state.locked = False
            # получим каждую запись
            for key in keys:
                if not key.startswith(self.key_prefix):
                    continue
                rid = int(key[len(self.key_prefix) :])
                try:
                    entry = await kv.get(key)
                except KeyValueError:
                    continue
                old_state = self._states.get(rid)
                if old_state is None:
                    old_state = ResourceState(resource_id=rid)
                    self._states[rid] = old_state
                old_state.version = entry.revision
                old_state.locked = True
            logger.info(
                "States reloaded from KV, total resources: %d",
                len(self._states),
            )

    async def on_kv_event(
        self,
        key: str,
        operation: Literal["PURGE", "PUT"] | None,
        revision: int,
    ) -> None:
        """
        Вызывается при событии подписки broker.subscriber(..., kv_watch).
        Обновляет/добавляет/удаляет ресурс в локальном хранилище состояний.
        """
        try:
            if not key.startswith(self.key_prefix):
                return
            rid = int(key[len(self.key_prefix) :])
            async with self._lock:
                state = self._states.get(rid)
                if state is None:
                    # добавляем новый ресурс
                    state = ResourceState(resource_id=rid)
                    self._states[rid] = state
                    logger.info("Discovered new resource %s via KV event", rid)
                if operation in ("DEL", "PURGE"):
                    state.version = None
                    state.locked = False
                    logger.debug(
                        "Resource %s unlocked via KV delete event", rid
                    )
                elif operation is None:
                    state.version = revision
                    state.locked = True
                    logger.debug(
                        "Resource %s locked by another, revision=%s",
                        rid,
                        revision,
                    )
        except Exception as e:
            logger.exception("Ошибка обработки NatsKvMessage: %s", e)

    async def lock(self, resource_id: int) -> bool:
        """
        Попытаться захватить ресурс в KV с помощью create.
        Возвращает True при успехе.
        """
        kv = await self._kv()
        key = self._key_name(resource_id)
        payload = self.instance_id.encode()
        try:
            ver = await kv.create(key, payload)
        except KeyValueError:
            logger.debug("Failed to lock %s: already taken", resource_id)
            return False
        except Exception as e:
            logger.error("Error creating lock for %s: %s", resource_id, e)
            return False
        async with self._lock:
            state = self._states.get(resource_id)
            if state is None:
                state = ResourceState(resource_id=resource_id)
                self._states[resource_id] = state
            state.version = ver
            state.locked = True
        logger.info("Locked resource %s, revision=%s", resource_id, ver)
        return True

    async def unlock(self, resource_id: int) -> None:
        """
        Освободить ресурс в KV и обновить локальное состояние.
        """
        kv = await self._kv()
        key = self._key_name(resource_id)
        try:
            await kv.purge(key)
        except KeyValueError as e:
            logger.warning("Ошибка при удалении ключа %s: %s", key, e)
        async with self._lock:
            state = self._states.get(resource_id)
            if state:
                state.version = None
                state.locked = False
        logger.info("Unlocked resource %s", resource_id)

    async def refresh(self) -> None:
        """
        Обновить TTL захваченного ресурса с помощью update.
        При ошибке последовательности — перезагрузить все стейты.
        """
        if not self._current:
            return
        kv = await self._kv()
        rid = self._current.resource_id
        key = self._key_name(rid)
        payload = self.instance_id.encode()
        last = self._current.version
        if last is None:
            return
        try:
            ver = await kv.update(key, payload, last=last)
        except KeyWrongLastSequenceError:
            logger.warning(
                "KeyWrongLastSequenceError for %s, reloading states", rid
            )
            await self._reload_states()
            return
        except KeyValueError as e:
            logger.error("Failed to refresh lock for %s: %s", rid, e)
            return
        async with self._lock:
            self._current.version = ver
        logger.debug("Refreshed TTL for resource %s, revision=%s", rid, ver)

    @asynccontextmanager
    async def session(
        self,
        timeout: float | None = None,  # noqa: ASYNC109
    ) -> AsyncIterator[int]:
        """
        Асинхронный контекстный менеджер. Захватывает свободный ресурс или ждёт
        до timeout.
        Возвращает resource_id.
        """
        deadline = (
            None
            if timeout is None
            else asyncio.get_event_loop().time() + timeout
        )
        picked: int | None = None
        try:
            while True:
                async with self._lock:
                    free = [
                        rid
                        for rid, st in self._states.items()
                        if not st.locked
                    ]
                if free:
                    picked = random.choice(free)  # noqa: S311
                    if await self.lock(picked):
                        async with self._lock:
                            self._current = self._states[picked]
                        break
                if deadline and asyncio.get_event_loop().time() > deadline:
                    raise TimeoutError("Timeout waiting for free resource")
                await asyncio.sleep(0.5)
            yield picked
        finally:
            if picked is not None:
                await self.unlock(picked)

    async def update_resources(self, new_ids: list[int]) -> None:
        """
        Обновить список ресурсов, добавив и удалив по разности множеств.
        Занятые ресурсы не удаляются.
        """
        new_set = set(new_ids)
        async with self._lock:
            old_set = set(self._states.keys())
            to_add = new_set - old_set
            to_remove = old_set - new_set
            for rid in to_add:
                self._states[rid] = ResourceState(resource_id=rid)
                logger.info("Added new resource %s", rid)
            for rid in to_remove:
                state = self._states[rid]
                if not state.locked:
                    del self._states[rid]
                    logger.info("Removed resource %s", rid)
                else:
                    logger.debug(
                        "Resource %s still locked, delaying removal until"
                        " unlock",
                        rid,
                    )

    async def __aenter__(self) -> Self:
        return await self.aenter()

    async def aenter(self) -> Self:
        # инициализация KV-клиента
        await self._kv()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any | None,
    ) -> None:
        return await self.aexit()

    async def aexit(self) -> None:
        if self._current is None:
            return
        try:
            await self.unlock(self._current.resource_id)
        except Exception as e:
            logger.error(
                "Error unlocking resource %s on exit: %s",
                self._current.resource_id,
                e,
            )
