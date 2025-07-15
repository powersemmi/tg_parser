"""
Скрипт добавляет в таблицу crawler.sessions новый телеграмм канал с необходимыми данными для авторизации.
Для работы с каналом необходимы следующие данные:
- API ID и хэш с https://my.telegram.org/apps
- Номер телефона
- Строка сессии (см. https://docs.telethon.dev/en/stable/concepts/sessions.html#string-sessions))
- Прокси, с которого заходить в аккаунт.
(желательно мобильное прокси с того же региона, в котором был зареган акк)
"""

import asyncio

import asyncpg
from telethon import TelegramClient
from telethon.sessions import StringSession

# Конфигурация
DB_DSN = "ваша строка подключения к базе"  # например, 'postgresql+asyncpg://user:password@host:port/dbname'
API_ID = ...  # Ваш API ID
API_HASH = "ваш API хэш"
PHONE = "ваш номер телефона"
PROXY = ("socks5", "proxy_host", 8080)  # Или None, если прокси не нужен


async def main():
    # Подключение к базе данных
    conn = await asyncpg.connect(dsn=DB_DSN)

    # Создание клиента и авторизация
    with TelegramClient(
        StringSession(),
        API_ID,
        API_HASH,
        proxy=None if PROXY is None else PROXY,
    ) as client:
        # Авторизация пользователя
        await client.start(phone=PHONE)

        # Получение строка сессии после авторизации
        session_str = client.session.save()

    # Вставляем или обновляем запись в базу данных
    await conn.execute(
        """
    INSERT INTO crawler.sessions (session, api_id, api_hash, tel, proxy)
    VALUES ($1, $2, $3, $4, $5)
    ON CONFLICT (tel) DO UPDATE SET
        session = EXCLUDED.session,
        api_id = EXCLUDED.api_id,
        api_hash = EXCLUDED.api_hash,
        proxy = EXCLUDED.proxy
    """,
        session_str,
        API_ID,
        API_HASH,
        PHONE,
        str(PROXY),
    )

    print("Сессия успешно добавлена в базу.")

    # Отключение клиента и соединения с БД
    await client.disconnect()
    await conn.close()


# Запуск
if __name__ == "__main__":
    asyncio.run(main())
