from typing import Annotated
from uuid import uuid4

from pydantic import AnyUrl, Field, NatsDsn, PostgresDsn, conlist
from pydantic_settings import BaseSettings, SettingsConfigDict


def str_uuid() -> str:
    """Generate a random UUID as a string.

    Returns:
        String representation of a UUID4.
    """
    return str(uuid4())


class Settings(BaseSettings):
    """Application settings configuration.

    Contains all configuration parameters for the crawler service,
    including connection details for various services and operational settings.
    """

    APP_NAME: str = "Chat Parser"
    DEBUG: bool = False
    POD_NAME: Annotated[str, Field(default_factory=str_uuid, alias="HOSTNAME")]

    TG_SESSION_NAME: str = "Crawler"

    PG_DSN: PostgresDsn
    PG_POOL_SIZE: int = 5
    PG_MAX_POOL_SIZE: int = 10

    CLICKHOUSE_URL: AnyUrl
    CH_POOL_SIZE: int = 10

    NATS_DSN: conlist(NatsDsn, min_length=1)  # type: ignore[valid-type]
    NATS_PREFIX: str = "crawler.tasks."
    NATS_STREAM: str = "CHAT_PARSER_TASKS"
    NATS_KV_BUCKET: str = "TG_RESOURCES"
    NATS_KV_TTL: int = 60
    NATS_MAX_DELIVERED_MESSAGES_COUNT: int = 10

    MESSAGE_SUBJECT: str = "telegram.message"
    MESSAGE_STREAM: str = "CHAT_PARSER_MESSAGES"
    MESSAGE_BATCH_SIZE: int = 20

    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="allow",
    )


settings: Settings = Settings()
