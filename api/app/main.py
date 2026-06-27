from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import SERVICE_NAME, SETTINGS
from app.models import HealthResponse, ReadyResponse, RootResponse, ServicesResponse
from app.services.model import ModelClient
from app.services.search import SearchClient
from app.websocket.chat import router as chat_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    http = httpx.AsyncClient(follow_redirects=True)
    app.state.model_client = ModelClient(http=http, settings=SETTINGS)
    app.state.search_client = SearchClient(http=http, settings=SETTINGS)
    try:
        yield
    finally:
        await http.aclose()


app = FastAPI(
    title="Aristotle Agent API",
    description="Agent orchestration service for Aristotle.",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=SETTINGS.cors_allow_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(chat_router)


@app.get("/", response_model=RootResponse)
async def root() -> RootResponse:
    return RootResponse(
        service=SERVICE_NAME,
        description="Agent API and WebSocket orchestration service for Aristotle.",
        endpoints={
            "health": "/healthz",
            "readiness": "/readyz",
            "services": "/services",
            "chat_websocket": "/ws/chat",
            "docs": "/docs",
        },
    )


@app.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    return HealthResponse(ok=True, service=SERVICE_NAME)


@app.get("/services", response_model=ServicesResponse)
async def services() -> ServicesResponse:
    model_client: ModelClient = app.state.model_client
    search_client: SearchClient = app.state.search_client
    return ServicesResponse(
        model=await model_client.status(),
        search=await search_client.status(),
    )


@app.get("/readyz", response_model=ReadyResponse)
async def readyz() -> ReadyResponse:
    service_status = await services()
    if not service_status.ok:
        raise HTTPException(
            status_code=503,
            detail=ReadyResponse(ok=False, services=service_status).model_dump(),
        )
    return ReadyResponse(ok=True, services=service_status)
