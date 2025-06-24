from typing import Annotated
from uuid import uuid4

from pydantic import (
    AnyUrl,
    Field,
    NatsDsn,
    PostgresDsn,
    conlist,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


def str_uuid() -> str:
    return str(uuid4())


class Settings(BaseSettings):
    # Service
    APP_NAME: str = "Chat Parser"
    DEBUG: bool = False
    POD_NAME: Annotated[str, Field(default_factory=str_uuid, alias="HOSTNAME")]
    # Telegram
    TG_SESSION_NAME: str = "Crawler"
    # Postgres
    PG_DSN: PostgresDsn
    PG_POOL_SIZE: int = 5
    PG_MAX_POOL_SIZE: int = 10
    # ClickHouse
    CLICKHOUSE_URL: AnyUrl
    CH_POOL_SIZE: int = 10
    # Nats
    NATS_DSN: conlist(NatsDsn, min_length=1)  # type: ignore[valid-type]
    NATS_PREFIX: str = "crawler.tasks."
    NATS_KV_BUCKET: str = "TG_RESOURCES"
    NATS_KV_TTL: int = 60

    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="allow",
    )


settings = Settings()
