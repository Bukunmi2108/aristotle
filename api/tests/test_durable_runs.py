import unittest
from types import SimpleNamespace
from typing import Any, cast

from app.agent.capabilities.replay_safe import ReplaySafeTools
from app.chat_runs import create_chat_run
from app.durable.workflow import _model_history
from app.events import EventSender
from app.models import ClientUserMessage


class FakeRunStore:
    def __init__(self):
        self.request: dict[str, Any] | None = None

    async def get_presentation(self, artifact_id: str):
        return None

    async def ensure_conversation(self, *args):
        return None

    async def list_files(self, conversation_id: str):
        return []

    async def create_message(self, **kwargs):
        return None

    async def attach_files_to_message(self, **kwargs):
        return None

    async def create_run(self, **kwargs):
        self.request = kwargs["request"]

    async def complete_run(self, *args):
        return None

    async def update_message(self, **kwargs):
        return None


class FakeDBOSClient:
    def __init__(self):
        self.options: dict[str, Any] | None = None
        self.args: tuple[Any, ...] = ()

    async def enqueue_async(self, options, *args):
        self.options = options
        self.args = args


class DurableRunTest(unittest.IsolatedAsyncioTestCase):
    async def test_start_persists_server_request_without_browser_history(self):
        store = FakeRunStore()
        client = FakeDBOSClient()
        message = ClientUserMessage.model_validate(
            {
                "type": "user.message",
                "message": "Research this",
                "conversation_id": "conv_1",
                "history": [{"role": "assistant", "content": "untrusted"}],
            }
        )

        created = await create_chat_run(cast(Any, store), cast(Any, client), message)

        self.assertNotIn("history", store.request or {})
        self.assertEqual(client.args, (created.run_id,))
        self.assertEqual(client.options["workflow_id"], created.run_id)

    async def test_server_history_builds_typed_model_messages(self):
        history = _model_history(
            [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "second"},
            ]
        )

        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].parts[0].content, "first")
        self.assertEqual(history[1].parts[0].content, "second")

    async def test_socket_delivery_failure_does_not_cancel_event_persistence(self):
        persisted: list[dict[str, Any]] = []

        class Store:
            async def append_event(self, event):
                persisted.append(event)

        async def disconnected(payload):
            raise ConnectionError("gone")

        events = EventSender(
            disconnected,
            conversation_id="conv_1",
            run_id="run_1",
            store=Store(),
        )
        await events.send("session.started")
        await events.send("agent.started")

        self.assertEqual(len(persisted), 2)
        self.assertTrue(persisted[0]["event_id"].startswith("evt_"))
        self.assertNotEqual(persisted[0]["event_id"], persisted[1]["event_id"])


class ReplaySafetyTest(unittest.IsolatedAsyncioTestCase):
    async def test_completed_tool_result_is_replayed_without_calling_handler(self):
        class Store:
            async def begin_tool_execution(self, **kwargs):
                return {"status": "complete", "result": {"value": 7}}, False

        deps = SimpleNamespace(document_store=Store(), run_id="run_1")
        ctx = SimpleNamespace(deps=deps, tool_call_id="call_1")
        called = False

        async def handler(args):
            nonlocal called
            called = True
            return {"value": 9}

        result = await ReplaySafeTools().wrap_tool_execute(
            cast(Any, ctx),
            call=cast(Any, None),
            tool_def=cast(Any, SimpleNamespace(name="search_web")),
            args={"query": "rome"},
            handler=handler,
        )

        self.assertEqual(result, {"value": 7})
        self.assertFalse(called)


if __name__ == "__main__":
    unittest.main()
