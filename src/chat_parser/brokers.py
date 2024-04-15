import logging

from faststream.rabbit.broker import RabbitBroker

from chat_parser.settings import settings

logger = logging.getLogger(__name__)
broker = RabbitBroker(
    url=settings.RABBIT_DSN.unicode_string(),
    logger=logger,
    graceful_timeout=30,
)
