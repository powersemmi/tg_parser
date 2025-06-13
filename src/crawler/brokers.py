import logging

from faststream.nats import JStream
from faststream.nats.broker import NatsBroker

from crawler.settings import settings

logger = logging.getLogger(__name__)
broker = NatsBroker(
    servers=[dsn.unicode_string() for dsn in settings.NATS_DSN],
    logger=logger,
    graceful_timeout=30,
)
parser_stream = JStream(name="CHAT_PARSER", subjects=["crawler.tasks.*"])
