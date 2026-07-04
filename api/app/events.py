from datetime import UTC, datetime
from typing import Any, Literal
from pydantic import BaseModel, Field


EventType = Literal[
    "session.started",
    "service.checking",
    "service.waking",
    "service.ready",
    "agent.started",
    "model.selected",
    "model.fallback",
    "model.first_token",
    "tool.started",
    "tool.result",
    "tool.error",
    "reasoning.delta",
    "message.delta",
    "message.completed",
    "session.completed",
    "error",
]


class Event(BaseModel):
    type: EventType
    sequence: int
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    conversation_id: str | None = None
    service: str | None = None
    provider: str | None = None
    model: str | None = None
    url: str | None = None
    tool: str | None = None
    input: dict[str, Any] | None = None
    result_count: int | None = None
    result_preview: list[dict[str, Any]] | None = None
    text: str | None = None
    message: str | None = None
    code: str | None = None
    reason: str | None = None
    latency_ms: int | None = None


class EventSender:
    def __init__(self, send_json, conversation_id: str):
        self._send_json = send_json
        self._sequence = 0
        self._conversation_id = conversation_id

    async def send(self, event_type: EventType, **kwargs: Any) -> None:
        self._sequence += 1
        event = Event(
            type=event_type,
            sequence=self._sequence,
            conversation_id=self._conversation_id,
            **kwargs,
        )
        await self._send_json(event.model_dump(exclude_none=True))
