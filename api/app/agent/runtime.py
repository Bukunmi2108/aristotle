from typing import Any

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

        await events.send(
            "agent.started",
            input={
                "web_tools_enabled": options.use_search,
                "max_search_results": options.max_search_results,
            },
        )

        async with agent.run_stream_events(
            user_message.message,
            deps=deps,
            model_settings={"temperature": self.settings.agent_temperature},
            conversation_id=user_message.conversation_id,
        ) as stream:
            async for event in stream:
                text_delta = await self._handle_event(event, events)
                if text_delta:
                    final_parts.append(text_delta)

        return "".join(final_parts)

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
