import logging

from faststream.nats.broker import NatsBroker

from crawler.settings import settings

logger = logging.getLogger(__name__)
broker = NatsBroker(
    servers=[dsn.unicode_string() for dsn in settings.NATS_DSN],
    logger=logger,
    graceful_timeout=30,
)
