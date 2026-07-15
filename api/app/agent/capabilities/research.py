import asyncio
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from pydantic import BaseModel, Field
from pydantic_ai import ToolDefinition
from pydantic_ai.toolsets.function import FunctionToolset
from pydantic_ai.tools import RunContext

from app.agent.capabilities.local_web import (
    FetchUrlResult,
    Freshness,
    LocalWebTools,
)
from app.agent.deps import AgentDeps
from app.models import SearchResponse, SearchResult


RESEARCH_TOOL_NAMES = {
    "search_web",
    "fetch_url",
    "search_multi_query",
    "extract_source_facts",
    "rank_sources",
    "build_citations",
}
TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "msclkid",
}
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
WORD_RE = re.compile(r"[a-z0-9]{3,}")


class ResearchFailure(BaseModel):
    operation: str
    input: str
    error: str


class SearchMultiQueryResult(BaseModel):
    goal: str
    queries: list[str]
    results: list[SearchResult]
    responses: list[SearchResponse]
    failures: list[ResearchFailure] = Field(default_factory=list)


class ResearchSource(BaseModel):
    url: str
    title: str | None = None
    content: str = ""
    snippet: str = ""
    source: str | None = None
    published_at: str | None = None
    score: float | None = None


class SourceFact(BaseModel):
    url: str
    title: str | None = None
    fact: str
    char_start: int
    char_end: int


class SourceFactsResult(BaseModel):
    url: str
    title: str | None = None
    facts: list[SourceFact]


class RankedSource(BaseModel):
    url: str
    title: str | None = None
    snippet: str = ""
    relevance_score: float
    reasons: list[str] = Field(default_factory=list)


class RankSourcesResult(BaseModel):
    goal: str
    sources: list[RankedSource]


class Citation(BaseModel):
    marker: str
    url: str
    title: str | None = None
    matched_terms: list[str] = Field(default_factory=list)


class CitationBuildResult(BaseModel):
    answer_draft: str
    citations: list[Citation]
    source_notes: list[str] = Field(default_factory=list)


@dataclass
class ResearchTools(LocalWebTools):
    max_queries_per_run: int = 4
    max_source_facts: int = 8
    max_citation_sources: int = 8

    def get_instructions(self):
        def instructions(ctx: RunContext[AgentDeps]) -> str | None:
            if not ctx.deps.web_tools_enabled:
                return None
            return (
                "Use search_web and fetch_url as primitive research tools. For broader "
                "research, use search_multi_query to search several focused queries, "
                "fetch_url to open one selected source at a time, rank_sources to prioritize "
                "evidence, extract_source_facts to pull concise source facts, and "
                "build_citations to map known source URLs into citation candidates. "
                "Do not invent citations. Treat failed fetches as source gaps and say "
                "what could not be verified when it matters."
            )

        return instructions

    def get_toolset(self) -> FunctionToolset[AgentDeps]:
        toolset = FunctionToolset[AgentDeps](
            id="research_tools",
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
            return await self.search_web_impl(
                ctx,
                query=query,
                max_results=max_results,
                freshness=freshness,
                domains=domains,
                tool_name="search_web",
            )

        @toolset.tool(
            name="fetch_url", strict=False, timeout=self.fetch_timeout_seconds
        )
        async def fetch_url(ctx: RunContext[AgentDeps], url: str) -> FetchUrlResult:
            """Fetch a public HTTP(S) URL and return readable page text."""
            return await self.fetch_url_impl(ctx, url=url, tool_name="fetch_url")

        @toolset.tool(name="search_multi_query", strict=False)
        async def search_multi_query(
            ctx: RunContext[AgentDeps],
            goal: str,
            queries: list[str],
            max_results_per_query: int = 3,
            freshness: Freshness | None = None,
            domains: list[str] | None = None,
        ) -> SearchMultiQueryResult:
            """Run several focused web searches, deduplicate URLs, and return source candidates."""
            capped_queries = _cap_unique_strings(queries, self.max_queries_per_run)
            await ctx.deps.events.send(
                "tool.started",
                tool="search_multi_query",
                input={
                    "goal": goal,
                    "queries": capped_queries,
                    "max_results_per_query": max_results_per_query,
                    "freshness": freshness,
                    "domains": domains or [],
                },
            )
            tasks = [
                self.search_web_impl(
                    ctx,
                    query=query,
                    max_results=max_results_per_query,
                    freshness=freshness,
                    domains=domains,
                    tool_name="search_multi_query.search",
                )
                for query in capped_queries
            ]
            responses: list[SearchResponse] = []
            failures: list[ResearchFailure] = []
            try:
                outcomes = await asyncio.gather(*tasks, return_exceptions=True)
            except asyncio.CancelledError:
                return SearchMultiQueryResult(
                    goal=goal,
                    queries=capped_queries,
                    results=[],
                    responses=[],
                    failures=[
                        ResearchFailure(
                            operation="search",
                            input=query,
                            error="Search batch was cancelled before completion.",
                        )
                        for query in capped_queries
                    ],
                )
            for query, outcome in zip(
                capped_queries,
                outcomes,
                strict=False,
            ):
                if isinstance(outcome, BaseException):
                    failures.append(
                        ResearchFailure(
                            operation="search",
                            input=query,
                            error=str(outcome),
                        )
                    )
                else:
                    responses.append(outcome)

            deduped: dict[str, SearchResult] = {}
            for response in responses:
                for result in response.results:
                    deduped.setdefault(_canonical_url(result.url), result)

            return SearchMultiQueryResult(
                goal=goal,
                queries=capped_queries,
                results=list(deduped.values()),
                responses=responses,
                failures=failures,
            )

        @toolset.tool(name="extract_source_facts", strict=False)
        async def extract_source_facts(
            ctx: RunContext[AgentDeps],
            source: ResearchSource,
        ) -> SourceFactsResult:
            """Extract concise factual statements from one fetched source."""
            await ctx.deps.events.send(
                "tool.started",
                tool="extract_source_facts",
                input={"url": source.url, "title": source.title},
            )
            facts = _extract_facts(source, max_facts=self.max_source_facts)
            return SourceFactsResult(url=source.url, title=source.title, facts=facts)

        @toolset.tool(name="rank_sources", strict=False)
        async def rank_sources(
            ctx: RunContext[AgentDeps],
            goal: str,
            sources: list[ResearchSource],
        ) -> RankSourcesResult:
            """Rank candidate sources against a research goal using deterministic relevance signals."""
            await ctx.deps.events.send(
                "tool.started",
                tool="rank_sources",
                input={"goal": goal, "source_count": len(sources)},
            )
            ranked = sorted(
                (_rank_source(goal, source) for source in sources),
                key=lambda item: item.relevance_score,
                reverse=True,
            )
            return RankSourcesResult(goal=goal, sources=ranked)

        @toolset.tool(name="build_citations", strict=False)
        async def build_citations(
            ctx: RunContext[AgentDeps],
            answer_draft: str,
            sources: list[ResearchSource],
        ) -> CitationBuildResult:
            """Build citation candidates from known source URLs for an answer draft."""
            await ctx.deps.events.send(
                "tool.started",
                tool="build_citations",
                input={
                    "answer_chars": len(answer_draft),
                    "source_count": len(sources),
                },
            )
            return _build_citations(
                answer_draft,
                sources,
                max_sources=self.max_citation_sources,
            )

        return toolset

    async def prepare_tools(
        self,
        ctx: RunContext[AgentDeps],
        tool_defs: list[ToolDefinition],
    ) -> list[ToolDefinition]:
        if ctx.deps.web_tools_enabled:
            return tool_defs
        return [tool for tool in tool_defs if tool.name not in RESEARCH_TOOL_NAMES]


def _cap_unique_strings(values: list[str], limit: int) -> list[str]:
    capped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(value.split())
        key = normalized.lower()
        if not normalized or key in seen:
            continue
        seen.add(key)
        capped.append(normalized)
        if len(capped) >= max(1, limit):
            break
    return capped


def _canonical_url(url: str) -> str:
    parsed = urlparse(str(url))
    params = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMS
    ]
    query = urlencode(params, doseq=True)
    path = parsed.path.rstrip("/") or "/"
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            "",
            query,
            "",
        )
    )


def _extract_facts(source: ResearchSource, max_facts: int) -> list[SourceFact]:
    content = source.content or source.snippet
    sentences = SENTENCE_RE.split(content)
    facts: list[SourceFact] = []
    cursor = 0
    for sentence in sentences:
        sentence = " ".join(sentence.split())
        if len(sentence) < 40:
            cursor += len(sentence) + 1
            continue
        start = content.find(sentence, cursor)
        if start < 0:
            start = cursor
        end = start + len(sentence)
        facts.append(
            SourceFact(
                url=source.url,
                title=source.title,
                fact=sentence[:600],
                char_start=start,
                char_end=end,
            )
        )
        cursor = end
        if len(facts) >= max(1, max_facts):
            break
    return facts


def _rank_source(goal: str, source: ResearchSource) -> RankedSource:
    goal_terms = _terms(goal)
    text = " ".join(
        part
        for part in [
            source.title or "",
            source.snippet,
            source.content[:4000],
            source.source or "",
        ]
        if part
    )
    text_terms = _terms(text)
    matches = sorted(goal_terms & text_terms)
    reasons: list[str] = []
    if matches:
        reasons.append(f"matches goal terms: {', '.join(matches[:8])}")
    if source.published_at:
        reasons.append(f"published_at: {source.published_at}")
    if source.source:
        reasons.append(f"source: {source.source}")

    base_score = len(matches) / max(1, len(goal_terms))
    search_score = min(float(source.score or 0), 10.0) / 100
    title_bonus = 0.15 if source.title and _terms(source.title) & goal_terms else 0
    return RankedSource(
        url=source.url,
        title=source.title,
        snippet=source.snippet or source.content[:280],
        relevance_score=round(base_score + search_score + title_bonus, 4),
        reasons=reasons,
    )


def _build_citations(
    answer_draft: str,
    sources: list[ResearchSource],
    max_sources: int,
) -> CitationBuildResult:
    answer_terms = _terms(answer_draft)
    ranked = sorted(
        sources,
        key=lambda source: len(answer_terms & _terms(_source_text(source))),
        reverse=True,
    )
    citations: list[Citation] = []
    notes: list[str] = []
    seen: set[str] = set()
    for source in ranked:
        canonical = _canonical_url(source.url)
        if canonical in seen:
            continue
        seen.add(canonical)
        matched_terms = sorted(answer_terms & _terms(_source_text(source)))[:12]
        if not matched_terms:
            notes.append(f"No direct term match for {source.url}")
            continue
        citations.append(
            Citation(
                marker=f"[{len(citations) + 1}]",
                url=source.url,
                title=source.title,
                matched_terms=matched_terms,
            )
        )
        if len(citations) >= max(1, max_sources):
            break

    return CitationBuildResult(
        answer_draft=answer_draft,
        citations=citations,
        source_notes=notes,
    )


def _source_text(source: ResearchSource) -> str:
    return " ".join(
        part
        for part in [source.title or "", source.snippet, source.content]
        if part
    )


def _terms(text: str) -> set[str]:
    return set(WORD_RE.findall(text.lower()))
