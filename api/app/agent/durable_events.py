from __future__ import annotations

from collections.abc import AsyncIterable
from typing import Any

from pydantic_ai.messages import (
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
)
from pydantic_ai.tools import RunContext

from app.agent.deps import AgentDeps
from app.events import EventType


async def journal_model_events(
    ctx: RunContext[AgentDeps], stream: AsyncIterable[Any]
) -> None:
    """Persist model text live inside the durable DBOS request step."""
    async for index, event in _enumerate(stream):
        event_type, text = _text_delta(event)
        if event_type is None or not text:
            continue
        await ctx.deps.events.send(
            event_type,
            text=text,
            event_key=(
                f"model:{ctx.deps.execution_pass}:{ctx.run_step}:{index}:{event_type}"
            ),
        )


async def _enumerate(stream: AsyncIterable[Any]):
    index = 0
    async for event in stream:
        yield index, event
        index += 1


def _text_delta(event: Any) -> tuple[EventType | None, str]:
    if isinstance(event, PartStartEvent):
        if isinstance(event.part, ThinkingPart):
            return "reasoning.delta", event.part.content or ""
        if isinstance(event.part, TextPart):
            return "message.delta", event.part.content or ""
    if isinstance(event, PartDeltaEvent):
        if isinstance(event.delta, ThinkingPartDelta):
            return "reasoning.delta", event.delta.content_delta or ""
        if isinstance(event.delta, TextPartDelta):
            return "message.delta", event.delta.content_delta or ""
    return None, ""
