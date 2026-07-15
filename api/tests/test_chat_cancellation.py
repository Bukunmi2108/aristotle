import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.websocket.chat import chat_websocket


class FakeReadyClient:
    async def is_ready(self) -> bool:
        return True


class FakeWebSocket:
    def __init__(self):
        self.sent: list[dict] = []
        self.app = SimpleNamespace(
            state=SimpleNamespace(
                model_client=FakeReadyClient(),
                search_client=FakeReadyClient(),
                sandbox_executor=None,
                store=None,
            )
        )

    async def accept(self) -> None:
        return None

    async def receive_json(self) -> dict:
        return {
            "type": "user.message",
            "message": "research this",
            "options": {"max_search_results": 5, "file_ids": []},
        }

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


class ChatWebsocketCancellationTest(unittest.IsolatedAsyncioTestCase):
    async def test_agent_cancellation_emits_clean_error(self):
        websocket = FakeWebSocket()

        async def cancelled_stream_response(*args, **kwargs):
            raise asyncio.CancelledError

        with patch(
            "app.websocket.chat.AristotleAgentRuntime.stream_response",
            cancelled_stream_response,
        ):
            await chat_websocket(websocket)

        errors = [event for event in websocket.sent if event["type"] == "error"]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["code"], "request_cancelled")


if __name__ == "__main__":
    unittest.main()
