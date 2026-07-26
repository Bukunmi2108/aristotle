import json
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse

from app.config import SERVICE_NAME, SETTINGS
from app.models import (
    ExecRequest,
    ExecResult,
    ExportDocumentRequest,
    ExportDocumentResponse,
    ListResponse,
    MoveRequest,
    OkResponse,
    PathRequest,
    WriteResponse,
)
from app.workspace import (
    InvalidConversationError,
    NotFoundError,
    PathEscapeError,
    WorkspaceError,
    WorkspaceManager,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.manager = WorkspaceManager(SETTINGS)
    yield


app = FastAPI(
    title="Aristotle Sandbox",
    description="Private code-execution + workspace service for Aristotle.",
    version="0.1.0",
    lifespan=lifespan,
)


def require_token(authorization: str | None = Header(default=None)) -> None:
    """Guard every workspace route with a bearer token.

    The sandbox is only reachable over the private internal network, but the
    token is a second lock so a misconfigured network never exposes raw code
    execution. When no token is configured (local dev) the guard is a no-op.
    """
    expected = SETTINGS.auth_token
    if expected is None:
        return
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="Invalid or missing token.")


def _manager(request: Request) -> WorkspaceManager:
    return request.app.state.manager


def _handle(exc: WorkspaceError) -> HTTPException:
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, (PathEscapeError, InvalidConversationError)):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@app.get("/")
async def root() -> dict:
    return {
        "service": SERVICE_NAME,
        "description": "Private code-execution + workspace service for Aristotle.",
        "endpoints": {
            "health": "/healthz",
            "readiness": "/readyz",
            "exec": "/workspaces/{conversation_id}/exec",
            "export": "/workspaces/{conversation_id}/export",
            "file": "/workspaces/{conversation_id}/file",
            "list": "/workspaces/{conversation_id}/list",
        },
    }


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, "service": SERVICE_NAME}


@app.get("/readyz")
async def readyz(request: Request) -> dict:
    manager = _manager(request)
    ready = manager.root.exists() and manager.root.is_dir()
    if not ready:
        raise HTTPException(status_code=503, detail="Workspace root unavailable.")
    return {"ok": True}


@app.post(
    "/workspaces/{conversation_id}/exec",
    response_model=ExecResult,
    dependencies=[Depends(require_token)],
)
async def exec_command(
    conversation_id: str, body: ExecRequest, request: Request
) -> ExecResult:
    try:
        return await _manager(request).exec(
            conversation_id, body.command, body.timeout_seconds
        )
    except WorkspaceError as exc:
        raise _handle(exc) from exc


@app.post(
    "/workspaces/{conversation_id}/exec_stream",
    dependencies=[Depends(require_token)],
)
async def exec_stream(
    conversation_id: str, body: ExecRequest, request: Request
) -> StreamingResponse:
    manager = _manager(request)

    async def lines():
        try:
            async for event in manager.exec_stream(
                conversation_id, body.command, body.timeout_seconds
            ):
                yield json.dumps(event) + "\n"
        except WorkspaceError as exc:
            yield json.dumps({"type": "error", "message": str(exc)}) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson")


@app.get(
    "/workspaces/{conversation_id}/list",
    response_model=ListResponse,
    dependencies=[Depends(require_token)],
)
async def list_dir(
    conversation_id: str, request: Request, path: str = Query(default=".")
) -> ListResponse:
    try:
        entries = _manager(request).list_dir(conversation_id, path)
        return ListResponse(path=path, entries=entries)
    except WorkspaceError as exc:
        raise _handle(exc) from exc


@app.get(
    "/workspaces/{conversation_id}/file",
    dependencies=[Depends(require_token)],
)
async def read_file(
    conversation_id: str, request: Request, path: str = Query(min_length=1)
) -> Response:
    try:
        data = _manager(request).read_file(conversation_id, path)
    except WorkspaceError as exc:
        raise _handle(exc) from exc
    return Response(content=data, media_type="application/octet-stream")


@app.put(
    "/workspaces/{conversation_id}/file",
    response_model=WriteResponse,
    dependencies=[Depends(require_token)],
)
async def write_file(
    conversation_id: str, request: Request, path: str = Query(min_length=1)
) -> WriteResponse:
    data = await request.body()
    try:
        size = _manager(request).write_file(conversation_id, path, data)
    except WorkspaceError as exc:
        raise _handle(exc) from exc
    return WriteResponse(path=path, size=size)


@app.post(
    "/workspaces/{conversation_id}/export",
    response_model=ExportDocumentResponse,
    dependencies=[Depends(require_token)],
)
async def export_document(
    conversation_id: str, body: ExportDocumentRequest, request: Request
) -> ExportDocumentResponse:
    try:
        return await _manager(request).export_document(
            conversation_id,
            body.source_path,
            body.output_path,
            body.title,
        )
    except WorkspaceError as exc:
        raise _handle(exc) from exc


@app.post(
    "/workspaces/{conversation_id}/mkdir",
    response_model=OkResponse,
    dependencies=[Depends(require_token)],
)
async def make_dir(
    conversation_id: str, body: PathRequest, request: Request
) -> OkResponse:
    try:
        _manager(request).make_dir(conversation_id, body.path)
    except WorkspaceError as exc:
        raise _handle(exc) from exc
    return OkResponse()


@app.post(
    "/workspaces/{conversation_id}/move",
    response_model=OkResponse,
    dependencies=[Depends(require_token)],
)
async def move_path(
    conversation_id: str, body: MoveRequest, request: Request
) -> OkResponse:
    try:
        _manager(request).move(conversation_id, body.src, body.dst)
    except WorkspaceError as exc:
        raise _handle(exc) from exc
    return OkResponse()


@app.delete(
    "/workspaces/{conversation_id}/file",
    response_model=OkResponse,
    dependencies=[Depends(require_token)],
)
async def delete_path(
    conversation_id: str, request: Request, path: str = Query(min_length=1)
) -> OkResponse:
    try:
        _manager(request).delete(conversation_id, path)
    except WorkspaceError as exc:
        raise _handle(exc) from exc
    return OkResponse()


@app.delete(
    "/workspaces/{conversation_id}",
    response_model=OkResponse,
    dependencies=[Depends(require_token)],
)
async def destroy_workspace(conversation_id: str, request: Request) -> OkResponse:
    try:
        _manager(request).destroy(conversation_id)
    except WorkspaceError as exc:
        raise _handle(exc) from exc
    return OkResponse()
