from typing import Any
from time import perf_counter
from urllib.parse import urlparse

from pydantic import BaseModel
from pydantic_ai import AgentRunResultEvent
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    PartDeltaEvent,
    PartStartEvent,
    RetryPromptPart,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    ToolCallPart,
    UserPromptPart,
)

from app.agent.deps import AgentDeps
from app.agent.factory import build_agent
from app.agent.model_trace import (
    ModelTrace,
    reset_model_trace,
    start_model_trace,
)
from app.config import ApiSettings
from app.db import PersistenceStore
from app.events import EventSender
from app.models import ClientUserMessage, SearchResponse
from app.services.sandbox_client import SandboxClient, Workspace
from app.services.search import SearchClient


MAX_HISTORY_CHARS = 24_000


class AristotleAgentRuntime:
    def __init__(
        self,
        search_client: SearchClient,
        settings: ApiSettings,
        document_store: PersistenceStore | None = None,
        sandbox_client: SandboxClient | None = None,
    ):
        self.search_client = search_client
        self.settings = settings
        self.document_store = document_store
        self.sandbox_client = sandbox_client

    async def stream_response(
        self, user_message: ClientUserMessage, events: EventSender
    ) -> str:
        trace, trace_token = start_model_trace(self.settings)
        try:
            agent = build_agent(self.settings)
            options = user_message.options
            if options.file_ids and self.document_store is None:
                raise RuntimeError("Document persistence is not configured.")
            prompt = await self._message_with_context(
                user_message.message,
                options.file_ids,
                user_message.conversation_id,
                user_message.active_artifact_id,
            )
            workspace = (
                Workspace(self.sandbox_client, user_message.conversation_id)
                if self.sandbox_client is not None
                and self.settings.workspace_enabled
                and user_message.conversation_id is not None
                else None
            )
            deps = AgentDeps(
                search_client=self.search_client,
                http_client=self.search_client.http,
                events=events,
                settings=self.settings,
                max_search_results=options.max_search_results,
                web_tools_enabled=True,
                document_store=self.document_store,
                file_ids=options.file_ids,
                workspace=workspace,
            )
            final_parts: list[str] = []
            model_started = perf_counter()
            model_selection_sent = False
            first_model_event_sent = False
            first_text_sent = False
            active_tool_calls: dict[str, str] = {}

            await events.send(
                "agent.started",
                input={
                    "web_tools_enabled": True,
                    "max_search_results": options.max_search_results,
                    "file_ids": options.file_ids,
                    "primary_model": trace.primary.model,
                    "fallback_model": trace.fallback.model if trace.fallback else None,
                    "history_messages": len(user_message.history),
                    "history_chars": sum(
                        len(message.content) for message in user_message.history
                    ),
                },
            )

            try:
                async with agent.run_stream_events(
                    prompt,
                    message_history=_message_history(user_message),
                    deps=deps,
                    model_settings={"temperature": self.settings.agent_temperature},
                    conversation_id=user_message.conversation_id,
                ) as stream:
                    async for event in stream:
                        if trace.selected and not model_selection_sent:
                            await _send_model_selection(events, trace)
                            model_selection_sent = True

                        if _is_model_event(event) and not first_model_event_sent:
                            if trace.selected and not model_selection_sent:
                                await _send_model_selection(events, trace)
                                model_selection_sent = True
                            await events.send(
                                "model.first_event",
                                provider=(
                                    trace.selected.provider if trace.selected else None
                                ),
                                model=trace.selected.model if trace.selected else None,
                                url=trace.selected.url if trace.selected else None,
                                latency_ms=int((perf_counter() - model_started) * 1000),
                            )
                            first_model_event_sent = True

                        if _has_stream_token(event) and not first_text_sent:
                            await events.send(
                                "model.first_text",
                                provider=(
                                    trace.selected.provider if trace.selected else None
                                ),
                                model=trace.selected.model if trace.selected else None,
                                url=trace.selected.url if trace.selected else None,
                                latency_ms=int((perf_counter() - model_started) * 1000),
                            )
                            first_text_sent = True

                        text_delta = await self._handle_event(
                            event, events, active_tool_calls
                        )
                        if text_delta:
                            final_parts.append(text_delta)
            except Exception as exc:
                for tool_call_id, tool_name in tuple(active_tool_calls.items()):
                    await events.send(
                        "tool.error",
                        tool=tool_name,
                        tool_call_id=tool_call_id,
                        message=str(exc),
                    )
                raise

            if trace.selected and not model_selection_sent:
                await _send_model_selection(events, trace)

            return "".join(final_parts)
        finally:
            reset_model_trace(trace_token)

    async def _message_with_context(
        self,
        message: str,
        file_ids: list[str],
        conversation_id: str | None = None,
        active_artifact_id: str | None = None,
    ) -> str:
        if self.document_store is None:
            return message

        sections: list[str] = []
        files: list[dict[str, Any]] = []
        for file_id in file_ids:
            record = await self.document_store.get_file(file_id)
            if record is not None:
                files.append(record)

        if files:
            file_lines = "\n".join(
                f"- {file['filename']} (file_id: {file['id']})" for file in files
            )
            sections.append(
                "Attached files for this user message:\n"
                f"{file_lines}\n\n"
                "Inspect attached files with DocumentTools before resolving vague "
                "references. Keep document evidence distinct from externally "
                "verified evidence."
            )

        if conversation_id:
            presentations = await self.document_store.list_presentations(
                conversation_id
            )
            latest_by_path: dict[str, dict[str, Any]] = {}
            for presentation in presentations:
                path = presentation["path"]
                current = latest_by_path.get(path)
                if current is None or presentation["version"] > current["version"]:
                    latest_by_path[path] = presentation
            recent = sorted(
                latest_by_path.values(),
                key=lambda item: str(item.get("created_at") or ""),
            )[-8:]
            active = next(
                (item for item in presentations if item["id"] == active_artifact_id),
                None,
            )
            if active is not None and all(
                item["id"] != active["id"] for item in recent
            ):
                recent = [*recent[-7:], active]
            if recent:
                artifact_lines = "\n".join(
                    "- "
                    + ("[active] " if item["id"] == active_artifact_id else "")
                    + f"{item['path']} (artifact_id: {item['id']}, "
                    + f"mime: {item['mime_type']}, version: {item['version']}, "
                    + f"title: {item.get('title') or 'untitled'}, "
                    + f"message_id: {item.get('message_id') or 'unknown'})"
                    for item in recent
                )
                sections.append(
                    "Trusted artifacts already presented in this conversation:\n"
                    f"{artifact_lines}\n\n"
                    "For follow-ups such as 'this', 'it', 'as PDF', or 'also as "
                    "Markdown', use the active artifact first, otherwise the newest "
                    "compatible artifact. Read the workspace path before modifying or "
                    "exporting it. A format-only request must reuse the existing "
                    "content and must not trigger new web research. Use export_document "
                    "when the user asks for Markdown and/or PDF; it presents every "
                    "successful requested format."
                )

        if not sections:
            return message
        return "\n\n".join(sections) + f"\n\nUser message:\n{message}"

    async def _message_with_file_context(
        self, message: str, file_ids: list[str]
    ) -> str:
        return await self._message_with_context(message, file_ids)

    async def _handle_event(
        self,
        event: Any,
        events: EventSender,
        active_tool_calls: dict[str, str] | None = None,
    ) -> str:
        if isinstance(event, FunctionToolCallEvent):
            if active_tool_calls is not None:
                active_tool_calls[event.part.tool_call_id] = event.part.tool_name
            await events.send(
                "tool.started",
                tool=event.part.tool_name,
                tool_call_id=event.part.tool_call_id,
                input=_tool_input(event.part),
            )
            return ""

        if isinstance(event, FunctionToolResultEvent):
            if active_tool_calls is not None:
                active_tool_calls.pop(event.part.tool_call_id, None)
            if isinstance(event.part, RetryPromptPart):
                await events.send(
                    "tool.error",
                    tool=event.part.tool_name,
                    tool_call_id=event.part.tool_call_id,
                    message=str(event.part.content),
                )
                return ""
            await events.send(
                "tool.result",
                tool=event.part.tool_name,
                tool_call_id=event.part.tool_call_id,
                result_count=_result_count(event.part.content),
                result_preview=_result_preview(event.part.content),
            )
            return ""

        if isinstance(event, AgentRunResultEvent):
            usage = event.result.usage
            await events.send(
                "run.usage",
                usage={
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "cache_read_tokens": usage.cache_read_tokens,
                    "cache_write_tokens": usage.cache_write_tokens,
                    "requests": usage.requests,
                    "tool_calls": usage.tool_calls,
                },
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


def _is_model_event(event: Any) -> bool:
    if isinstance(event, FunctionToolCallEvent):
        return True
    return isinstance(event, PartStartEvent) and isinstance(
        event.part, ThinkingPart | TextPart | ToolCallPart
    )


def _tool_input(part: ToolCallPart) -> dict[str, Any]:
    if isinstance(part.args, dict):
        return part.args
    if isinstance(part.args, str) and part.args:
        return {"raw": part.args}
    return {}


def _result_count(content: Any) -> int | None:
    if isinstance(content, SearchResponse):
        return len(content.results)
    data = _as_dict(content)
    if data is not None and _is_fetch_result(data):
        return 0 if _is_failed_fetch_result(data) else 1
    if data:
        for key in ("results", "chunks", "sources", "citations", "facts", "failures"):
            values = data.get(key)
            if isinstance(values, list):
                return len(values)
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


def _message_history(user_message: ClientUserMessage) -> list[ModelMessage]:
    history: list[ModelMessage] = []
    remaining_chars = MAX_HISTORY_CHARS

    for message in reversed(user_message.history):
        content = message.content.strip()
        if not content:
            continue

        if len(content) > remaining_chars:
            content = content[-remaining_chars:].strip()
        if not content:
            break

        if message.role == "user":
            history.append(ModelRequest(parts=[UserPromptPart(content=content)]))
        else:
            history.append(ModelResponse(parts=[TextPart(content=content)]))

        remaining_chars -= len(content)
        if remaining_chars <= 0:
            break

    history.reverse()
    return history


def _result_preview(content: Any) -> list[dict[str, Any]] | None:
    if isinstance(content, SearchResponse):
        return [
            _source_preview(result.model_dump(), status="searched")
            for result in content.results[:5]
        ]

    data = _as_dict(content)
    if not data:
        return None

    if _is_fetch_result(data):
        status = "failed" if _is_failed_fetch_result(data) else "fetched"
        source = _source_preview(data, status=status)
        return [source] if source else None

    preview: list[dict[str, Any]] = []
    for key, status in (
        ("results", "searched"),
        ("chunks", "fetched"),
        ("sources", "ranked"),
        ("citations", "cited"),
        ("facts", "cited"),
    ):
        values = data.get(key)
        if not isinstance(values, list):
            continue
        for item in values:
            if isinstance(item, dict):
                source = _source_preview(item, status=status)
                if source:
                    preview.append(source)

    failures = data.get("failures")
    if isinstance(failures, list):
        for failure in failures:
            if isinstance(failure, dict) and failure.get("input"):
                preview.append(
                    {
                        "title": failure.get("input"),
                        "url": failure.get("input"),
                        "snippet": failure.get("error"),
                        "status": "failed",
                    }
                )

    return _dedupe_source_previews(preview)[:8] or None


def _as_dict(content: Any) -> dict[str, Any] | None:
    if isinstance(content, dict):
        return content
    if isinstance(content, BaseModel):
        return content.model_dump()
    return None


def _is_fetch_result(data: dict[str, Any] | None) -> bool:
    return bool(
        data
        and isinstance(data.get("url"), str)
        and "content" in data
        and "content_chars" in data
    )


def _is_failed_fetch_result(data: dict[str, Any]) -> bool:
    title = data.get("title")
    content = data.get("content")
    return (
        title is None
        and isinstance(content, str)
        and content.startswith("Fetch failed for ")
    )


def _source_preview(item: dict[str, Any], *, status: str) -> dict[str, Any]:
    source_type = item.get("source_type")
    file_id = item.get("file_id")
    chunk_id = item.get("chunk_id") or item.get("id")
    if source_type == "document" or file_id or item.get("locator"):
        title = item.get("title") or item.get("filename")
        snippet = item.get("snippet") or item.get("text_preview") or item.get("quote")
        return {
            "id": chunk_id if isinstance(chunk_id, str) else item.get("id"),
            "title": title if isinstance(title, str) else "Document",
            "url": None,
            "domain": None,
            "source": "document",
            "source_type": "document",
            "file_id": file_id if isinstance(file_id, str) else None,
            "chunk_id": chunk_id if isinstance(chunk_id, str) else None,
            "locator": item.get("locator")
            if isinstance(item.get("locator"), str)
            else None,
            "page": item.get("page"),
            "section": item.get("section"),
            "row_start": item.get("row_start"),
            "row_end": item.get("row_end"),
            "snippet": _preview_text(snippet),
            "status": status,
        }

    url = item.get("url")
    if not isinstance(url, str) or not url:
        return {}

    title = item.get("title")
    snippet = item.get("snippet") or item.get("fact") or item.get("content")
    source = {
        "title": title if isinstance(title, str) else None,
        "url": url,
        "domain": _domain(url),
        "source": item.get("source") if isinstance(item.get("source"), str) else None,
        "snippet": _preview_text(snippet),
        "status": status,
    }
    if item.get("marker"):
        source["marker"] = item.get("marker")
    return source


def _dedupe_source_previews(
    previews: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for preview in previews:
        url = preview.get("url")
        fallback_id = preview.get("chunk_id") or preview.get("id")
        if isinstance(url, str) and url:
            key = url
        elif isinstance(fallback_id, str) and fallback_id:
            key = fallback_id
        else:
            continue
        current = deduped.get(key, {})
        deduped[key] = {
            **preview,
            **{key: value for key, value in current.items() if value},
        }
    return list(deduped.values())


def _domain(url: str) -> str | None:
    parsed = urlparse(url)
    if not parsed.hostname:
        return None
    return parsed.hostname.removeprefix("www.")


def _preview_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    if not cleaned:
        return None
    return cleaned[:280]
