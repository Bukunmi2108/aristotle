import asyncio
import logging
from datetime import UTC, datetime
from hashlib import sha256
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
    "model.first_event",
    "model.first_text",
    "run.usage",
    "tool.started",
    "tool.result",
    "tool.error",
    "terminal.output",
    "workspace.present",
    "reasoning.delta",
    "message.delta",
    "message.completed",
    "session.completed",
    "error",
]


logger = logging.getLogger(__name__)


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
    tool_call_id: str | None = None
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
    usage: dict[str, int] | None = None
    stream: str | None = None
    artifact_id: str | None = None
    path: str | None = None
    mime_type: str | None = None
    title: str | None = None
    version: int | None = None
    size_bytes: int | None = None


class EventSender:
    def __init__(
        self,
        send_json,
        conversation_id: str,
        *,
        run_id: str | None = None,
        message_id: str | None = None,
        store: Any = None,
        namespace: str = "stream",
    ):
        self._send_json = send_json
        self._sequence = 0
        self._conversation_id = conversation_id
        self._run_id = run_id
        self._message_id = message_id
        self._store = store
        self._namespace = namespace
        self._lock = asyncio.Lock()

    @property
    def run_id(self) -> str | None:
        return self._run_id

    @property
    def message_id(self) -> str | None:
        return self._message_id

    async def send(self, event_type: EventType, **kwargs: Any) -> None:
        async with self._lock:
            self._sequence += 1
            event_key = kwargs.pop("event_key", None)
            identity = event_key or f"{self._namespace}:{self._sequence}"
            event = Event(
                event_id=(
                    "evt_"
                    + sha256(f"{self._run_id}:{identity}".encode()).hexdigest()[:32]
                    if self._run_id is not None
                    else f"evt_{uuid4().hex}"
                ),
                type=event_type,
                sequence=self._sequence,
                conversation_id=self._conversation_id,
                run_id=kwargs.pop("run_id", self._run_id),
                message_id=kwargs.pop("message_id", self._message_id),
                **kwargs,
            )
            payload = event.model_dump(exclude_none=True)
            if self._store is not None:
                stored = await self._store.append_event(payload)
                if isinstance(stored, dict):
                    payload = stored
            if self._send_json is not None:
                try:
                    await self._send_json(payload)
                except Exception:  # noqa: BLE001 - the journal outlives any transport
                    logger.info(
                        "Event delivery detached; run remains active",
                        extra={"run_id": self._run_id, "event_type": event_type},
                    )
                    self._send_json = None
