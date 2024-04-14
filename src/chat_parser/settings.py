from pydantic import AmqpDsn, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import make_url

from chat_parser.types import LimitedInt


class Settings(BaseSettings):
    # Service
    APP_NAME: str = "Chat Parser"
    DEBUG: bool = False
    MESSAGE_REQUEST_LIMIT: LimitedInt = 200
    # Telegram
    TG_SESSION_NAME: str = "Crawler"
    TG_API_ID: int
    TG_API_HASH: str
    TG_PHONE_NUMBER: str
    TG_PASSWORD: str
    # Postgres
    PG_DSN: PostgresDsn
    PG_POOL_SIZE: int = 5
    PG_MAX_POOL_SIZE: int = 10
    # Rabbit
    RABBIT_DSN: AmqpDsn

    model_config = SettingsConfigDict(
        case_sensitive=True,
        secrets_dir="/run/secrets",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    @classmethod
    @field_validator("PG_DSN", check_fields=False)
    def set_driver_name(cls, val: str) -> str:
        return str(make_url(val).set(drivername="postgresql+asyncpg"))


settings = Settings()
