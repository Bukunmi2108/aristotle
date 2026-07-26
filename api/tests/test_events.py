import asyncio
import unittest
from types import SimpleNamespace

from pydantic_ai import AgentRunResultEvent, RunUsage
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    RetryPromptPart,
    ToolCallPart,
    ToolReturnPart,
)

from app.agent.runtime import AristotleAgentRuntime
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

    async def test_runtime_pairs_tool_lifecycle_by_call_id(self):
        sender = SlowSender()
        events = EventSender(sender.send_json, conversation_id="conv_1")
        active_tool_calls: dict[str, str] = {}

        await AristotleAgentRuntime._handle_event(
            None,
            FunctionToolCallEvent(
                ToolCallPart(
                    tool_name="search_web",
                    args={"query": "roman history"},
                    tool_call_id="call_1",
                )
            ),
            events,
            active_tool_calls,
        )
        self.assertEqual(active_tool_calls, {"call_1": "search_web"})
        await AristotleAgentRuntime._handle_event(
            None,
            FunctionToolResultEvent(
                ToolReturnPart(
                    tool_name="search_web",
                    content={"results": []},
                    tool_call_id="call_1",
                )
            ),
            events,
            active_tool_calls,
        )

        self.assertEqual(
            [(event["type"], event["tool_call_id"]) for event in sender.sent],
            [("tool.started", "call_1"), ("tool.result", "call_1")],
        )
        self.assertEqual(sender.sent[0]["input"], {"query": "roman history"})
        self.assertEqual(active_tool_calls, {})

    async def test_runtime_resolves_retry_as_tool_error_with_call_id(self):
        sender = SlowSender()
        events = EventSender(sender.send_json, conversation_id="conv_1")

        await AristotleAgentRuntime._handle_event(
            None,
            FunctionToolResultEvent(
                RetryPromptPart(
                    content="search unavailable",
                    tool_name="search_web",
                    tool_call_id="call_2",
                )
            ),
            events,
        )

        self.assertEqual(sender.sent[0]["type"], "tool.error")
        self.assertEqual(sender.sent[0]["tool_call_id"], "call_2")
        self.assertEqual(sender.sent[0]["message"], "search unavailable")

    async def test_runtime_emits_provider_run_usage(self):
        sender = SlowSender()
        events = EventSender(sender.send_json, conversation_id="conv_1")
        usage = RunUsage(
            input_tokens=120,
            output_tokens=45,
            cache_read_tokens=20,
            requests=3,
            tool_calls=2,
        )

        await AristotleAgentRuntime._handle_event(
            None,
            AgentRunResultEvent(result=SimpleNamespace(usage=usage)),
            events,
        )

        self.assertEqual(sender.sent[0]["type"], "run.usage")
        self.assertEqual(sender.sent[0]["usage"]["input_tokens"], 120)
        self.assertEqual(sender.sent[0]["usage"]["output_tokens"], 45)
        self.assertEqual(sender.sent[0]["usage"]["requests"], 3)
        self.assertEqual(sender.sent[0]["usage"]["tool_calls"], 2)


if __name__ == "__main__":
    unittest.main()
