import asyncio
from collections.abc import Awaitable, Callable
from time import monotonic

from app.config import ApiSettings
from app.errors import ServiceWakeTimeoutError
from app.events import EventSender


ReadyCheck = Callable[[], Awaitable[bool]]


async def wait_for_service_ready(
    service: str,
    is_ready: ReadyCheck,
    settings: ApiSettings,
    events: EventSender | None = None,
) -> None:
    if events is not None:
        await events.send("service.checking", service=service)

    if await is_ready():
        if events is not None:
            await events.send("service.ready", service=service)
        return

    if events is not None:
        await events.send("service.waking", service=service)

    deadline = monotonic() + settings.wake_timeout_seconds
    while monotonic() < deadline:
        await asyncio.sleep(settings.wake_poll_interval_seconds)
        if await is_ready():
            if events is not None:
                await events.send("service.ready", service=service)
            return

    raise ServiceWakeTimeoutError(service)
