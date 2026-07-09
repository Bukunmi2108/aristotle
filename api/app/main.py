from contextlib import asynccontextmanager
from pathlib import Path
from shutil import rmtree
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from app.config import SERVICE_NAME, SETTINGS
from app.db import PersistenceStore, close_store, create_store
from app.documents import (
    chunks_to_records,
    infer_mime_type,
    parse_document_file,
    validate_upload,
)
from app.models import (
    FileRecord,
    FileUploadResponse,
    HealthResponse,
    ReadyResponse,
    RenameConversationRequest,
    RootResponse,
    ServicesResponse,
)
from app.services.model import ModelClient
from app.services.search import SearchClient
from app.websocket.chat import router as chat_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    http = httpx.AsyncClient(follow_redirects=True)
    store = await create_store(SETTINGS)
    app.state.model_client = ModelClient(http=http, settings=SETTINGS)
    app.state.search_client = SearchClient(http=http, settings=SETTINGS)
    app.state.store = store
    try:
        yield
    finally:
        await close_store(store)
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
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
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
            "conversations": "/conversations",
            "files": "/files",
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


@app.get("/conversations")
async def conversations() -> dict:
    store = _require_store()
    return {"conversations": await store.list_conversations()}


@app.get("/conversations/{conversation_id}")
async def conversation(conversation_id: str) -> dict:
    store = _require_store()
    record = await store.get_conversation(conversation_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return {"conversation": record}


@app.patch("/conversations/{conversation_id}")
async def rename_conversation(
    conversation_id: str,
    request: RenameConversationRequest,
) -> dict:
    store = _require_store()
    renamed = await store.rename_conversation(conversation_id, request.title.strip())
    if not renamed:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    record = await store.get_conversation(conversation_id)
    return {"conversation": record}


@app.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str) -> dict:
    store = _require_store()
    deleted = await store.delete_conversation(conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return {"ok": True}


@app.get("/conversations/{conversation_id}/messages")
async def conversation_messages(conversation_id: str) -> dict:
    store = _require_store()
    return {"messages": await store.list_messages(conversation_id)}


@app.post("/files", response_model=FileUploadResponse)
async def upload_file(
    request: Request,
    filename: str = Query(min_length=1, max_length=240),
    conversation_id: str | None = None,
) -> FileUploadResponse:
    store = _require_store()
    data = await request.body()
    mime_type = infer_mime_type(
        filename,
        request.headers.get("content-type"),
    )
    try:
        validate_upload(filename, len(data), SETTINGS)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    file_id = f"file_{uuid4().hex}"
    upload_dir = Path(SETTINGS.file_storage_dir) / file_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    storage_path = upload_dir / "original"
    storage_path.write_bytes(data)

    if conversation_id:
        await store.ensure_conversation(conversation_id, "Document chat")

    file_record = await store.create_file(
        file_id=file_id,
        filename=filename,
        mime_type=mime_type,
        size_bytes=len(data),
        storage_path=str(storage_path),
    )
    if conversation_id:
        await store.attach_file_to_conversation(conversation_id, file_id)

    await _parse_and_store_file(store, file_record)
    refreshed_file = await store.get_file(file_id)
    return FileUploadResponse(
        file=FileRecord.model_validate(refreshed_file or file_record),
    )


@app.delete("/files/{file_id}")
async def delete_file(file_id: str) -> dict:
    store = _require_store()
    file_record = await store.get_file(file_id)
    if file_record is None:
        raise HTTPException(status_code=404, detail="File not found.")
    deleted = await store.delete_file(file_id)
    if deleted:
        path = Path(file_record["storage_path"]).parent
        if path.exists():
            rmtree(path, ignore_errors=True)
    return {"ok": deleted}


@app.get("/runs/{run_id}")
async def run(run_id: str) -> dict:
    store = _require_store()
    record = await store.get_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return {"run": record}


@app.get("/runs/{run_id}/events")
async def run_events(run_id: str, after_event_id: str | None = None) -> dict:
    store = _require_store()
    return {"events": await store.list_events(run_id, after_event_id)}


def _require_store() -> PersistenceStore:
    store = getattr(app.state, "store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Persistence is not configured.")
    return store


async def _parse_and_store_file(
    store: PersistenceStore,
    file_record: dict,
) -> None:
    try:
        parsed = parse_document_file(
            Path(file_record["storage_path"]),
            filename=file_record["filename"],
            mime_type=file_record["mime_type"],
            settings=SETTINGS,
        )
        document_id = f"doc_{uuid4().hex}"
        chunks = chunks_to_records(parsed.chunks, file_id=file_record["id"])[
            : SETTINGS.max_chunks_per_file
        ]
        await store.replace_document(
            document_id=document_id,
            file_id=file_record["id"],
            title=parsed.title,
            text_chars=len(parsed.text),
            parser=parsed.parser,
            chunks=chunks,
        )
    except Exception as exc:
        await store.mark_file_parse_failed(file_record["id"], str(exc))
