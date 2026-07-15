import asyncio
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

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
    event_id: str = Field(default_factory=lambda: f"evt_{uuid4().hex}")
    type: EventType
    sequence: int
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    conversation_id: str | None = None
    run_id: str | None = None
    message_id: str | None = None
    service: str | None = None
    provider: str | None = None
    model: str | None = None
    url: str | None = None
    tool: str | None = None
    input: dict[str, Any] | None = None
    result_count: int | None = None
    result_preview: list[dict[str, Any]] | None = None
    artifacts: list[dict[str, Any]] | None = None
    output: dict[str, Any] | None = None
    text: str | None = None
    message: str | None = None
    code: str | None = None
    reason: str | None = None
    latency_ms: int | None = None


class EventSender:
    def __init__(
        self,
        send_json,
        conversation_id: str,
        *,
        run_id: str | None = None,
        message_id: str | None = None,
        store: Any = None,
    ):
        self._send_json = send_json
        self._sequence = 0
        self._conversation_id = conversation_id
        self._run_id = run_id
        self._message_id = message_id
        self._store = store
        self._lock = asyncio.Lock()

    @property
    def run_id(self) -> str | None:
        return self._run_id

    async def send(self, event_type: EventType, **kwargs: Any) -> None:
        async with self._lock:
            self._sequence += 1
            event = Event(
                type=event_type,
                sequence=self._sequence,
                conversation_id=self._conversation_id,
                run_id=kwargs.pop("run_id", self._run_id),
                message_id=kwargs.pop("message_id", self._message_id),
                **kwargs,
            )
            payload = event.model_dump(exclude_none=True)
            if self._store is not None:
                await self._store.append_event(payload)
            await self._send_json(payload)
