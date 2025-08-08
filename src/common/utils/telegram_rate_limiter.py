import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from telethon import TelegramClient
from telethon.errors import FloodWaitError

logger = logging.getLogger(__name__)

T = TypeVar("T")


class TelegramRateLimiter:
    """
    Класс для управления ограничениями скорости при работе с Telegram API.
    """

    def __init__(
        self,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        jitter: bool = True,
    ):
        """
        Args:
            base_delay: Базовая задержка между запросами в секундах
            max_delay: Максимальная задержка при exponential backoff
            jitter: Добавлять ли случайность к задержке
        """
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self._last_request_time = 0.0

    def _calculate_delay(self, attempt: int = 0) -> float:
        """Вычисляет задержку для следующего запроса."""
        delay = min(self.base_delay * (2**attempt), self.max_delay)

        if self.jitter:
            # Добавляем случайность ±25%
            jitter_range = delay * 0.25
            delay += random.uniform(-jitter_range, jitter_range)  # noqa: S311

        return max(delay, 0.1)  # Минимум 0.1 секунды

    async def _wait_if_needed(self, delay: float) -> None:
        """Ожидает если нужно соблюсти интервал между запросами."""
        current_time = asyncio.get_event_loop().time()
        time_since_last = current_time - self._last_request_time

        if time_since_last < delay:
            wait_time = delay - time_since_last
            logger.debug("Rate limiting: waiting %.2fs", wait_time)
            await asyncio.sleep(wait_time)

        self._last_request_time = asyncio.get_event_loop().time()

    async def execute_with_rate_limit(
        self,
        func: Callable[[], Awaitable[T]],
        max_retries: int = 3,
        custom_delay: float | None = None,
    ) -> T:
        """
        Выполняет функцию с соблюдением ограничений скорости.

        Args:
            func: Функция для выполнения
            max_retries: Максимальное количество повторных
                         попыток при FloodWait
            custom_delay: Кастомная задержка вместо базовой

        Returns:
            Результат выполнения функции

        Raises:
            FloodWaitError: Если превышено максимальное количество попыток
        """
        delay = custom_delay or self.base_delay
        last_error = ValueError("Unknown error")
        for attempt in range(max_retries + 1):
            try:
                await self._wait_if_needed(delay)
                return await func()

            except FloodWaitError as e:
                if attempt >= max_retries:
                    logger.error(
                        "Max retries exceeded for FloodWait. "
                        "Seconds to wait: %s",
                        e.seconds,
                    )
                    raise
                # добавляем немного больше времени
                wait_time = e.seconds + random.uniform(1, 5)  # noqa: S311
                logger.warning(
                    "FloodWait encountered, waiting %.2fs (attempt %d/%d)",
                    wait_time,
                    attempt + 1,
                    max_retries,
                )
                await asyncio.sleep(wait_time)

                # Увеличиваем задержку для следующих попыток
                delay = self._calculate_delay(attempt + 1)
                last_error = e
        raise ValueError from last_error


# Глобальный экземпляр rate limiter'а
rate_limiter = TelegramRateLimiter(
    # 2 секунды между запросами (безопасно для 20 запросов/мин лимита)
    base_delay=2.0,
    max_delay=30.0,
    jitter=True,
)


async def rate_limited_get_entity(
    client: TelegramClient, entity_input: str | int
) -> Any:
    """Получает сущность с соблюдением ограничений скорости."""
    return await rate_limiter.execute_with_rate_limit(
        lambda: client.get_entity(entity_input),
        max_retries=3,
    )


async def rate_limited_get_input_entity(
    client: TelegramClient, entity_input: str | int
) -> Any:
    """Получает input сущность с соблюдением ограничений скорости."""
    return await rate_limiter.execute_with_rate_limit(
        lambda: client.get_input_entity(entity_input),
        max_retries=3,
    )
