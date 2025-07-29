import logging
from typing import Annotated

from fast_depends import Depends
from faststream import Context
from faststream.nats import KvWatch, NatsMessage, NatsRouter

from common.utils.nats.resource_manager import ResourceLockManager
from crawler.settings import settings

router: NatsRouter = NatsRouter()


logger = logging.getLogger(__name__)


@router.subscriber(
    f"{settings.NATS_PREFIX}*", kv_watch=KvWatch(settings.NATS_KV_BUCKET)
)
async def update_keys_task(
    msg: str,
    raw: NatsMessage,
    rlm: Annotated[ResourceLockManager, Depends(Context)],
) -> None:
    if msg != settings.APP_NAME:
        return
    await rlm.on_kv_event(
        key=raw.raw_message.key,  # type:ignore[attr-defined]
        operation=raw.raw_message.operation,  # type:ignore[attr-defined]
        revision=raw.raw_message.revision,  # type:ignore[attr-defined]
    )
