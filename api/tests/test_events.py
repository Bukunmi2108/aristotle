import asyncio
import unittest

from app.events import EventSender


class SlowSender:
    """send_json that yields control mid-send, to expose interleaving bugs
    if EventSender.send() weren't serialized under concurrent callers."""

    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        await asyncio.sleep(0)
        self.sent.append(payload)


class EventSenderConcurrencyTest(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_sends_are_serialized_with_unique_sequences(self):
        sender = SlowSender()
        events = EventSender(sender.send_json, conversation_id="conv_1")

        await asyncio.gather(
            events.send("service.checking", service="model"),
            events.send("service.checking", service="search"),
        )

        sequences = [payload["sequence"] for payload in sender.sent]
        self.assertEqual(sequences, sorted(set(sequences)))
        self.assertEqual(len(sequences), 2)

        services_sent = [payload["service"] for payload in sender.sent]
        self.assertEqual(set(services_sent), {"model", "search"})


if __name__ == "__main__":
    unittest.main()
