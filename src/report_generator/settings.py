from pydantic import (
    AnyUrl,
    NatsDsn,
    PostgresDsn,
    conlist,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Service
    APP_NAME: str = "Chat Parser"
    DEBUG: bool = False
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
    NATS_PREFIX: str = "report_generator.tasks."
    NATS_BUCKET: str

    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=".env",
        env_file_encoding="utf-8",
    )


settings = Settings()
