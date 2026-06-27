import time
from contextlib import asynccontextmanager
import httpx
from fastapi import Depends, FastAPI, Request
from app.config import SERVICE_NAME, SETTINGS
from app.models import HealthResponse, ReadinessResponse, RootResponse, SearchRequest, SearchResponse
from app.searxng import SearxngClient, searxng_params


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
    return ReadinessResponse(ok=True, service=SERVICE_NAME, searxng_url=SETTINGS.searxng_internal_url)


@app.post("/search", response_model=SearchResponse)
async def search(
    search_request: SearchRequest,
    searxng: SearxngClient = Depends(get_searxng),
) -> SearchResponse:
    started = time.perf_counter()
    payload = await searxng.search(searxng_params(search_request))
    results, engines = payload.normalize(search_request)
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    return SearchResponse.from_results(
        request=search_request,
        results=results,
        engines=engines,
        elapsed_ms=elapsed_ms,
    )
