import ipaddress
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel
from pydantic_ai import ToolDefinition
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.toolsets.function import FunctionToolset
from pydantic_ai.tools import RunContext

from app.agent.deps import AgentDeps
from app.models import SearchResponse, SearchToolRequest
from app.services.wake import wait_for_service_ready


Freshness = Literal["day", "month", "year"]
WEB_TOOL_NAMES = {"search_web", "fetch_url"}
PRIVATE_HOSTS = {"localhost", "0.0.0.0"}
TEXT_SPACE_RE = re.compile(r"\s+")


class FetchUrlResult(BaseModel):
    url: str
    title: str | None = None
    content: str
    content_chars: int
    truncated: bool
    content_type: str | None = None


@dataclass
class LocalWebTools(AbstractCapability[AgentDeps]):
    max_search_results: int = 5
    max_fetch_bytes: int = 200_000
    max_fetch_chars: int = 12_000
    fetch_timeout_seconds: float = 20

    def get_instructions(self):
        def instructions(ctx: RunContext[AgentDeps]) -> str | None:
            if not ctx.deps.web_tools_enabled:
                return None
            return (
                "Use search_web for current facts, public references, source-grounded "
                "answers, or when the user asks you to search. Prefer short, direct "
                "queries. Do not set freshness unless the user explicitly asks for "
                "today, recent, past month, or past year results. Use exact URLs from "
                "search results; do not invent citations. If results are empty or weak, "
                "retry once with a simpler query before answering."
            )

        return instructions

    def get_toolset(self) -> FunctionToolset[AgentDeps]:
        toolset = FunctionToolset[AgentDeps](
            id="local_web_tools",
            timeout=max(self.fetch_timeout_seconds, 1),
            strict=False,
        )

        @toolset.tool(name="search_web", strict=False)
        async def search_web(
            ctx: RunContext[AgentDeps],
            query: str,
            max_results: int = 5,
            freshness: Freshness | None = None,
            domains: list[str] | None = None,
        ) -> SearchResponse:
            """Search the web for current facts, sources, and references."""
            max_allowed = min(self.max_search_results, ctx.deps.max_search_results)
            request = SearchToolRequest(
                query=query,
                max_results=max(1, min(max_results, max_allowed)),
                freshness=freshness,
                domains=domains or [],
            )
            await ctx.deps.events.send(
                "tool.started",
                tool="search_web",
                input=request.model_dump(exclude_none=True),
            )
            try:
                await wait_for_service_ready(
                    service="search",
                    is_ready=ctx.deps.search_client.is_ready,
                    settings=ctx.deps.settings,
                    events=ctx.deps.events,
                )
                return await ctx.deps.search_client.search(request)
            except Exception as exc:
                await ctx.deps.events.send(
                    "tool.error", tool="search_web", message=str(exc)
                )
                raise

        @toolset.tool(
            name="fetch_url", strict=False, timeout=self.fetch_timeout_seconds
        )
        async def fetch_url(ctx: RunContext[AgentDeps], url: str) -> FetchUrlResult:
            """Fetch a public HTTP(S) URL and return readable page text."""
            await ctx.deps.events.send(
                "tool.started", tool="fetch_url", input={"url": url}
            )
            try:
                _validate_public_http_url(url)
                raw, final_url, content_type, truncated = await _read_limited(
                    ctx,
                    url,
                    max_bytes=self.max_fetch_bytes,
                )
                _validate_public_http_url(final_url)
                title, content = _extract_content(raw, content_type)
                content = content[: self.max_fetch_chars]
                return FetchUrlResult(
                    url=final_url,
                    title=title,
                    content=content,
                    content_chars=len(content),
                    truncated=truncated or len(content) >= self.max_fetch_chars,
                    content_type=content_type,
                )
            except Exception as exc:
                await ctx.deps.events.send(
                    "tool.error", tool="fetch_url", message=str(exc)
                )
                raise

        return toolset

    async def prepare_tools(
        self,
        ctx: RunContext[AgentDeps],
        tool_defs: list[ToolDefinition],
    ) -> list[ToolDefinition]:
        if ctx.deps.web_tools_enabled:
            return tool_defs
        return [tool for tool in tool_defs if tool.name not in WEB_TOOL_NAMES]


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title: str | None = None
        self._in_title = False
        self._skip_depth = 0
        self._parts: list[str] = []
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in {"p", "br", "li", "h1", "h2", "h3", "h4", "tr"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str):
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False
            self.title = _clean_text(" ".join(self._title_parts)) or None
        if tag in {"p", "li", "h1", "h2", "h3", "h4", "tr"}:
            self._parts.append("\n")

    def handle_data(self, data: str):
        if self._skip_depth:
            return
        if self._in_title:
            self._title_parts.append(data)
        else:
            self._parts.append(data)

    def text(self) -> str:
        return _clean_text(" ".join(self._parts))


async def _read_limited(
    ctx: RunContext[AgentDeps],
    url: str,
    max_bytes: int,
) -> tuple[bytes, str, str | None, bool]:
    chunks: list[bytes] = []
    total = 0

    async with ctx.deps.http_client.stream(
        "GET",
        url,
        timeout=ctx.deps.settings.web_fetch_timeout_seconds,
        headers={"User-Agent": "AristotleBot/0.1"},
        follow_redirects=False,
    ) as response:
        response.raise_for_status()
        content_type = response.headers.get("content-type")
        async for chunk in response.aiter_bytes():
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                remaining = max_bytes - sum(len(part) for part in chunks)
                if remaining > 0:
                    chunks.append(chunk[:remaining])
                return b"".join(chunks), str(response.url), content_type, True
            chunks.append(chunk)

        return b"".join(chunks), str(response.url), content_type, False


def _extract_content(raw: bytes, content_type: str | None) -> tuple[str | None, str]:
    text = raw.decode("utf-8", errors="replace")
    if content_type and "html" not in content_type.lower():
        return None, _clean_text(text)

    parser = _TextExtractor()
    parser.feed(text)
    return parser.title, parser.text()


def _validate_public_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only public http and https URLs are supported.")

    hostname = parsed.hostname.lower()
    if hostname in PRIVATE_HOSTS or hostname.endswith(".local"):
        raise ValueError("Private or local hostnames are not allowed.")

    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        return

    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
        raise ValueError("Private or local IP addresses are not allowed.")


def _clean_text(text: str) -> str:
    lines = [TEXT_SPACE_RE.sub(" ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)
