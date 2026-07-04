from typing import Any
from time import perf_counter

from pydantic_ai.messages import (
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
)

from app.agent.deps import AgentDeps
from app.agent.factory import build_agent
from app.agent.model_trace import (
    ModelTrace,
    reset_model_trace,
    start_model_trace,
)
from app.config import ApiSettings
from app.events import EventSender
from app.models import ClientUserMessage, SearchResponse
from app.services.search import SearchClient


class AristotleAgentRuntime:
    def __init__(self, search_client: SearchClient, settings: ApiSettings):
        self.search_client = search_client
        self.settings = settings

    async def stream_response(
        self, user_message: ClientUserMessage, events: EventSender
    ) -> str:
        trace, trace_token = start_model_trace(self.settings)
        try:
            agent = build_agent(self.settings)
            options = user_message.options
            deps = AgentDeps(
                search_client=self.search_client,
                http_client=self.search_client.http,
                events=events,
                settings=self.settings,
                max_search_results=options.max_search_results,
                web_tools_enabled=options.use_search,
            )
            final_parts: list[str] = []
            model_started = perf_counter()
            model_selection_sent = False
            first_token_sent = False

            await events.send(
                "agent.started",
                input={
                    "web_tools_enabled": options.use_search,
                    "max_search_results": options.max_search_results,
                    "primary_model": trace.primary.model,
                    "fallback_model": trace.fallback.model if trace.fallback else None,
                },
            )

            async with agent.run_stream_events(
                user_message.message,
                deps=deps,
                model_settings={"temperature": self.settings.agent_temperature},
                conversation_id=user_message.conversation_id,
            ) as stream:
                async for event in stream:
                    if trace.selected and not model_selection_sent:
                        await _send_model_selection(events, trace)
                        model_selection_sent = True

                    if _has_stream_token(event) and not first_token_sent:
                        if trace.selected and not model_selection_sent:
                            await _send_model_selection(events, trace)
                            model_selection_sent = True
                        await events.send(
                            "model.first_token",
                            provider=trace.selected.provider if trace.selected else None,
                            model=trace.selected.model if trace.selected else None,
                            url=trace.selected.url if trace.selected else None,
                            latency_ms=int((perf_counter() - model_started) * 1000),
                        )
                        first_token_sent = True

                    text_delta = await self._handle_event(event, events)
                    if text_delta:
                        final_parts.append(text_delta)

            if trace.selected and not model_selection_sent:
                await _send_model_selection(events, trace)

            return "".join(final_parts)
        finally:
            reset_model_trace(trace_token)

    async def _handle_event(self, event: Any, events: EventSender) -> str:
        if isinstance(event, FunctionToolResultEvent):
            await events.send(
                "tool.result",
                tool=event.part.tool_name,
                result_count=_result_count(event.part.content),
                result_preview=_result_preview(event.part.content),
            )
            return ""

        if isinstance(event, PartStartEvent):
            if isinstance(event.part, ThinkingPart) and event.part.content:
                await events.send("reasoning.delta", text=event.part.content)
            if isinstance(event.part, TextPart) and event.part.content:
                await events.send("message.delta", text=event.part.content)
                return event.part.content
            return ""

        if isinstance(event, PartDeltaEvent):
            if isinstance(event.delta, ThinkingPartDelta) and event.delta.content_delta:
                await events.send("reasoning.delta", text=event.delta.content_delta)
            if isinstance(event.delta, TextPartDelta) and event.delta.content_delta:
                await events.send("message.delta", text=event.delta.content_delta)
                return event.delta.content_delta

        return ""


def _result_count(content: Any) -> int | None:
    if isinstance(content, SearchResponse):
        return len(content.results)
    if isinstance(content, dict):
        results = content.get("results")
        if isinstance(results, list):
            return len(results)
    return None


async def _send_model_selection(events: EventSender, trace: ModelTrace) -> None:
    if trace.selected is None:
        return

    if trace.selected.provider == "fallback" and trace.fallback_reason:
        await events.send(
            "model.fallback",
            provider=trace.selected.provider,
            model=trace.selected.model,
            url=trace.selected.url,
            reason=trace.fallback_reason,
            latency_ms=trace.selected_latency_ms,
        )

    await events.send(
        "model.selected",
        provider=trace.selected.provider,
        model=trace.selected.model,
        url=trace.selected.url,
        latency_ms=trace.selected_latency_ms,
    )


def _has_stream_token(event: Any) -> bool:
    if isinstance(event, PartStartEvent):
        return (
            isinstance(event.part, ThinkingPart)
            and bool(event.part.content)
            or isinstance(event.part, TextPart)
            and bool(event.part.content)
        )

    if isinstance(event, PartDeltaEvent):
        return (
            isinstance(event.delta, ThinkingPartDelta)
            and bool(event.delta.content_delta)
            or isinstance(event.delta, TextPartDelta)
            and bool(event.delta.content_delta)
        )

    return False


def _result_preview(content: Any) -> list[dict[str, Any]] | None:
    if isinstance(content, SearchResponse):
        return [
            {
                "title": result.title,
                "url": result.url,
                "source": result.source,
            }
            for result in content.results[:3]
        ]

    if isinstance(content, dict):
        results = content.get("results")
        if isinstance(results, list):
            preview = []
            for result in results[:3]:
                if isinstance(result, dict):
                    preview.append(
                        {
                            "title": result.get("title"),
                            "url": result.get("url"),
                            "source": result.get("source"),
                        }
                    )
            return preview

    return None
