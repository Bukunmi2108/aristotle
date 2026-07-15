import unittest
from types import SimpleNamespace
from typing import Any, cast

from app.errors import ServiceWakeTimeoutError
from app.events import EventSender
from app.services.wake import wait_for_service_ready


class RecordingSender:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


def make_settings(*, wake_timeout_seconds: float, wake_poll_interval_seconds: float):
    return cast(
        Any,
        SimpleNamespace(
            wake_timeout_seconds=wake_timeout_seconds,
            wake_poll_interval_seconds=wake_poll_interval_seconds,
        ),
    )


class WaitForServiceReadyTest(unittest.IsolatedAsyncioTestCase):
    async def test_ready_immediately_emits_checking_then_ready(self):
        sender = RecordingSender()
        events = EventSender(sender.send_json, conversation_id="conv_1")

        async def is_ready() -> bool:
            return True

        await wait_for_service_ready(
            service="model",
            is_ready=is_ready,
            settings=make_settings(
                wake_timeout_seconds=1, wake_poll_interval_seconds=0.01
            ),
            events=events,
        )

        types = [event["type"] for event in sender.sent]
        self.assertEqual(types, ["service.checking", "service.ready"])

    async def test_not_ready_then_ready_emits_waking_before_ready(self):
        sender = RecordingSender()
        events = EventSender(sender.send_json, conversation_id="conv_1")
        attempts = {"count": 0}

        async def is_ready() -> bool:
            attempts["count"] += 1
            return attempts["count"] > 1

        await wait_for_service_ready(
            service="search",
            is_ready=is_ready,
            settings=make_settings(
                wake_timeout_seconds=1, wake_poll_interval_seconds=0.01
            ),
            events=events,
        )

        types = [event["type"] for event in sender.sent]
        self.assertEqual(types, ["service.checking", "service.waking", "service.ready"])

    async def test_never_ready_raises_timeout(self):
        sender = RecordingSender()
        events = EventSender(sender.send_json, conversation_id="conv_1")

        async def is_ready() -> bool:
            return False

        with self.assertRaises(ServiceWakeTimeoutError) as ctx:
            await wait_for_service_ready(
                service="model",
                is_ready=is_ready,
                settings=make_settings(
                    wake_timeout_seconds=0.03, wake_poll_interval_seconds=0.01
                ),
                events=events,
            )

        self.assertEqual(ctx.exception.service, "model")
        types = [event["type"] for event in sender.sent]
        self.assertEqual(types[0], "service.checking")
        self.assertIn("service.waking", types)
        self.assertNotIn("service.ready", types)


if __name__ == "__main__":
    unittest.main()
