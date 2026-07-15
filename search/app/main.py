import time
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
from fastapi import Depends, FastAPI, Request

from app.config import SERVICE_NAME, SETTINGS
from app.models import (
    HealthResponse,
    ReadinessResponse,
    RootResponse,
    SearchRequest,
    SearchResponse,
)
from app.searxng import SearxngClient, searxng_params

GENERAL_ENGINE_PROFILE = ["bing", "presearch"]


@dataclass(frozen=True)
class SearchAttempt:
    request: SearchRequest
    reason: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    http = httpx.AsyncClient(timeout=SETTINGS.http_timeout(), follow_redirects=True)
    app.state.searxng = SearxngClient(http=http, base_url=SETTINGS.searxng_internal_url)
    try:
        yield
    finally:
        await http.aclose()


app = FastAPI(
    title="Aristotle Search Service",
    description="SearXNG-backed search tool API for Aristotle.",
    version="0.1.0",
    lifespan=lifespan,
)


def get_searxng(request: Request) -> SearxngClient:
    return request.app.state.searxng


@app.get("/", response_model=RootResponse)
async def root() -> RootResponse:
    return RootResponse(
        service=SERVICE_NAME,
        description="SearXNG-backed search tool service for Aristotle.",
        endpoints={
            "health": "/healthz",
            "readiness": "/readyz",
            "search": "/search",
            "docs": "/docs",
        },
    )


@app.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    return HealthResponse(ok=True, service=SERVICE_NAME)


@app.get("/readyz", response_model=ReadinessResponse)
async def readyz(searxng: SearxngClient = Depends(get_searxng)) -> ReadinessResponse:
    await searxng.search(
        {
            "q": "ping",
            "format": "json",
            "language": "en",
            "safesearch": "1",
        },
    )
    return ReadinessResponse(
        ok=True,
        service=SERVICE_NAME,
        searxng_url=SETTINGS.searxng_internal_url,
    )


@app.post("/search", response_model=SearchResponse)
async def search(
    search_request: SearchRequest,
    searxng: SearxngClient = Depends(get_searxng),
) -> SearchResponse:
    started = time.perf_counter()
    attempts = _build_search_attempts(search_request)
    attempt_metadata: list[dict] = []
    last_engines: list[str] = []
    last_results = []

    for index, attempt in enumerate(attempts):
        attempt_started = time.perf_counter()
        payload = await searxng.search(searxng_params(attempt.request))
        results, engines = payload.normalize(attempt.request)
        last_results = results
        last_engines = engines
        attempt_metadata.append(
            _attempt_metadata(
                attempt=attempt,
                result_count=len(results),
                engines=engines,
                unresponsive_engines=payload.unresponsive_engines,
                elapsed_ms=int((time.perf_counter() - attempt_started) * 1000),
            )
        )

        if results:
            return SearchResponse.from_results(
                request=search_request,
                results=results,
                engines=engines,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                fallback_used=index > 0,
                unresponsive_engines=_unique_unresponsive(attempt_metadata),
                attempts=attempt_metadata,
            )

    return SearchResponse.from_results(
        request=search_request,
        results=last_results,
        engines=last_engines,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        fallback_used=len(attempt_metadata) > 1,
        unresponsive_engines=_unique_unresponsive(attempt_metadata),
        attempts=attempt_metadata,
        empty_reason="all_search_attempts_empty",
    )


def _build_search_attempts(request: SearchRequest) -> list[SearchAttempt]:
    attempts: list[SearchAttempt] = []
    seen: set[tuple] = set()

    def add(candidate: SearchRequest, reason: str) -> None:
        key = (
            candidate.query,
            candidate.category,
            candidate.freshness,
            candidate.language,
            tuple(candidate.domains),
            tuple(candidate.engines),
        )
        if key in seen:
            return
        seen.add(key)
        attempts.append(SearchAttempt(request=candidate, reason=reason))

    if request.engines:
        add(request, "requested_engines")
        if request.freshness is not None:
            add(
                request.model_copy(update={"freshness": None}),
                "requested_engines_without_freshness",
            )
        return attempts

    if request.domains:
        add(request, "domain_default_engines")
        if request.freshness is not None:
            add(request.model_copy(update={"freshness": None}), "domain_without_freshness")
        if request.language != "all":
            add(
                request.model_copy(update={"language": "all"}),
                "domain_relaxed_language",
            )
        return attempts

    if request.category == "general":
        add(
            request.model_copy(update={"engines": GENERAL_ENGINE_PROFILE}),
            "general_profile",
        )
        if request.language != "all":
            add(
                request.model_copy(
                    update={"engines": GENERAL_ENGINE_PROFILE, "language": "all"}
                ),
                "general_profile_relaxed_language",
            )
        if request.freshness is not None:
            add(
                request.model_copy(update={"engines": GENERAL_ENGINE_PROFILE, "freshness": None}),
                "general_profile_without_freshness",
            )
        add(request, "default_engines")
        if request.freshness is not None:
            add(
                request.model_copy(update={"freshness": None}),
                "default_engines_without_freshness",
            )
        return attempts

    add(request, f"{request.category}_default_engines")
    if request.freshness is not None:
        add(
            request.model_copy(update={"freshness": None}),
            f"{request.category}_without_freshness",
        )
    if request.category == "news":
        add(
            request.model_copy(
                update={"category": "general", "engines": GENERAL_ENGINE_PROFILE}
            ),
            "news_general_profile_fallback",
        )
        add(
            request.model_copy(update={"category": "general"}),
            "news_general_default_fallback",
        )
    return attempts


def _attempt_metadata(
    *,
    attempt: SearchAttempt,
    result_count: int,
    engines: list[str],
    unresponsive_engines: list[str],
    elapsed_ms: int,
) -> dict:
    return {
        "reason": attempt.reason,
        "category": attempt.request.category,
        "freshness": attempt.request.freshness,
        "language": attempt.request.language,
        "engines_requested": attempt.request.engines,
        "engines_returned": engines,
        "unresponsive_engines": unresponsive_engines,
        "result_count": result_count,
        "elapsed_ms": elapsed_ms,
    }


def _unique_unresponsive(attempts: list[dict]) -> list[str]:
    seen: list[str] = []
    for attempt in attempts:
        engines = attempt.get("unresponsive_engines", [])
        if not isinstance(engines, list):
            continue
        for engine in engines:
            if isinstance(engine, str) and engine and engine not in seen:
                seen.append(engine)
    return seen
