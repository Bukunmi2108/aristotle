import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from shutil import rmtree
from uuid import uuid4

import httpx
from dbos import DBOSClient
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

from app.chat_runs import DocumentScopeError, create_chat_run
from app.config import SERVICE_NAME, SETTINGS
from app.db import PersistenceStore, close_store, create_store
from app.documents import (
    chunks_to_records,
    infer_mime_type,
    parse_document_file,
    validate_upload,
)
from app.models import (
    ClientUserMessage,
    FileRecord,
    FileUploadResponse,
    HealthResponse,
    ReadyResponse,
    RenameConversationRequest,
    RootResponse,
    RunCreatedResponse,
    RunSteerRequest,
    ServicesResponse,
    ServiceStatus,
)
from app.services.model import ModelClient
from app.services.sandbox_client import SandboxClient, SandboxError
from app.services.search import SearchClient
from app.websocket.chat import router as chat_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    http = httpx.AsyncClient(follow_redirects=True)
    store = await create_store(SETTINGS)
    app.state.model_client = ModelClient(http=http, settings=SETTINGS)
    app.state.search_client = SearchClient(http=http, settings=SETTINGS)
    app.state.sandbox_client = (
        SandboxClient(http=http, settings=SETTINGS)
        if SETTINGS.workspace_enabled
        else None
    )
    app.state.store = store
    app.state.dbos_client = (
        DBOSClient(system_database_url=SETTINGS.database_url)
        if SETTINGS.database_url
        else None
    )
    try:
        yield
    finally:
        if app.state.dbos_client is not None:
            app.state.dbos_client.destroy()
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
            "chat_runs": "/runs",
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
    sandbox_client: SandboxClient | None = getattr(app.state, "sandbox_client", None)
    checks = [model_client.status(), search_client.status()]
    if SETTINGS.workspace_enabled and sandbox_client is not None:
        checks.append(sandbox_client.status())
    statuses = await asyncio.gather(*checks)
    sandbox_status = (
        statuses[2]
        if len(statuses) == 3
        else ServiceStatus(
            ok=False,
            service="sandbox",
            url=SETTINGS.sandbox_service_base_url,
            error="Workspace service is unavailable.",
        )
        if SETTINGS.workspace_enabled
        else None
    )
    store: PersistenceStore | None = getattr(app.state, "store", None)
    worker_status = None
    if store is not None and hasattr(store, "worker_ready"):
        worker_ready = await store.worker_ready(
            application_version=getattr(
                SETTINGS, "dbos_application_version", "aristotle-v1"
            )
        )
        worker_status = ServiceStatus(
            ok=worker_ready,
            service="worker",
            url="dbos://aristotle-agent",
            error=None if worker_ready else "Durable worker heartbeat is stale.",
        )
    return ServicesResponse(
        model=statuses[0],
        search=statuses[1],
        sandbox=sandbox_status,
        worker=worker_status,
        poll_interval_seconds=SETTINGS.wake_poll_interval_seconds,
        wake_timeout_seconds=SETTINGS.wake_timeout_seconds,
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
    dbos_client: DBOSClient | None = getattr(app.state, "dbos_client", None)
    if dbos_client is not None:
        for run_id in await store.list_active_run_ids(conversation_id):
            await dbos_client.cancel_workflow_async(run_id)
    deleted = await store.delete_conversation(conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    sandbox_client = getattr(app.state, "sandbox_client", None)
    if sandbox_client is not None:
        await sandbox_client.destroy(conversation_id)
    return {"ok": True}


@app.get("/conversations/{conversation_id}/messages")
async def conversation_messages(conversation_id: str) -> dict:
    store = _require_store()
    return {"messages": await store.list_messages(conversation_id)}


@app.get("/conversations/{conversation_id}/presentations")
async def conversation_presentations(conversation_id: str) -> dict:
    store = _require_store()
    return {"presentations": await store.list_presentations(conversation_id)}


@app.get("/presentations/{presentation_id}/content")
async def presentation_file(
    presentation_id: str,
    download: int = 0,
) -> Response:
    """Serve the immutable bytes captured when the agent presented a file."""
    store = _require_store()
    sandbox_client = _require_sandbox()
    presentation = await store.get_presentation(presentation_id)
    if presentation is None:
        raise HTTPException(status_code=404, detail="Artifact is not available.")
    path = presentation.get("snapshot_path") or presentation["path"]
    return await _presented_file_response(
        sandbox_client,
        presentation,
        path,
        download=download,
    )


@app.get("/workspace/{conversation_id}/file")
async def workspace_file(
    conversation_id: str,
    path: str = Query(min_length=1),
    download: int = 0,
) -> Response:
    """Serve a workspace file to the browser — but only if the agent presented it.

    The user never enumerates the filesystem; this endpoint refuses any path the
    agent did not explicitly present, so the browser can never read arbitrary
    workspace files.
    """
    store = _require_store()
    sandbox_client = _require_sandbox()
    presentation = await store.latest_presentation(conversation_id, path)
    if presentation is None:
        raise HTTPException(status_code=404, detail="File is not available.")
    return await _presented_file_response(
        sandbox_client,
        presentation,
        presentation.get("snapshot_path") or path,
        download=download,
    )


async def _presented_file_response(
    sandbox_client: SandboxClient,
    presentation: dict,
    read_path: str,
    *,
    download: int,
) -> Response:
    conversation_id = presentation["conversation_id"]
    try:
        data = await sandbox_client.read_file(conversation_id, read_path)
    except SandboxError as exc:
        raise HTTPException(status_code=404, detail="File is missing.") from exc
    except Exception as exc:
        # The path was presented, so an unexpected failure here is the sandbox
        # being unreachable — surface it as 502, don't disguise it as 404.
        logger.exception("Failed to read presented workspace file %r", read_path)
        raise HTTPException(
            status_code=502, detail="Workspace is temporarily unavailable."
        ) from exc

    filename = presentation["path"].rsplit("/", 1)[-1].replace('"', "")
    disposition = "attachment" if download else "inline"
    return Response(
        content=data,
        media_type=presentation["mime_type"],
        headers={
            "Content-Disposition": f'{disposition}; filename="{filename}"',
            # Untrusted agent content: nosniff + a CSP sandbox that gives it an
            # opaque origin (no app/API access) while still running its scripts.
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox allow-scripts allow-popups allow-forms",
        },
    )


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


@app.post("/runs", response_model=RunCreatedResponse, status_code=202)
async def start_run(user_message: ClientUserMessage) -> RunCreatedResponse:
    store = _require_store()
    if not await store.worker_ready(
        application_version=SETTINGS.dbos_application_version
    ):
        raise HTTPException(status_code=503, detail="Durable worker is not ready.")
    dbos_client: DBOSClient | None = getattr(app.state, "dbos_client", None)
    if dbos_client is None:
        raise HTTPException(
            status_code=503, detail="Durable execution is not configured."
        )
    try:
        return await create_chat_run(store, dbos_client, user_message)
    except DocumentScopeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/runs/{run_id}/events")
async def run_events(run_id: str, after_event_id: str | None = None) -> dict:
    store = _require_store()
    return {"events": await store.list_events(run_id, after_event_id)}


@app.get("/runs/{run_id}/events/stream")
async def stream_run_events(
    run_id: str,
    request: Request,
    after_event_id: str | None = None,
) -> StreamingResponse:
    store = _require_store()
    if await store.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    cursor = request.headers.get("last-event-id") or after_event_id

    async def event_stream():
        nonlocal cursor
        while True:
            events = await store.list_events(run_id, cursor)
            for event in events:
                cursor = event["event_id"]
                yield (
                    f"id: {cursor}\n"
                    f"event: {event['type']}\n"
                    f"data: {json.dumps(event)}\n\n"
                )
            if any(event["type"] in {"session.completed", "error"} for event in events):
                return
            record = await store.get_run(run_id)
            if (
                record is None or record["status"] in {"complete", "error", "cancelled"}
            ) and not events:
                return
            if await request.is_disconnected():
                return
            yield ": keepalive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.delete("/runs/{run_id}")
async def cancel_run(run_id: str) -> dict:
    store = _require_store()
    record = await store.get_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    if record["status"] in {"complete", "error", "cancelled"}:
        return {"ok": True, "status": record["status"]}
    dbos_client: DBOSClient | None = getattr(app.state, "dbos_client", None)
    if dbos_client is not None:
        await dbos_client.cancel_workflow_async(run_id)
    await store.complete_run(run_id, "cancelled", "Cancelled by user.")
    await store.update_message(
        message_id=record["assistant_message_id"],
        content="",
        status="stopped",
    )
    return {"ok": True, "status": "cancelled"}


@app.post("/runs/{run_id}/steer", status_code=202)
async def steer_run(run_id: str, steering: RunSteerRequest) -> dict:
    store = _require_store()
    record = await store.get_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    if record["status"] not in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="Run is no longer accepting input.")
    input_id = f"input_{uuid4().hex}"
    await store.add_run_input(
        input_id=input_id,
        run_id=run_id,
        content=steering.message.strip(),
    )
    return {"input_id": input_id, "status": "pending"}


def _require_sandbox() -> SandboxClient:
    sandbox_client = getattr(app.state, "sandbox_client", None)
    if sandbox_client is None:
        raise HTTPException(status_code=503, detail="Workspace is not configured.")
    return sandbox_client


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
