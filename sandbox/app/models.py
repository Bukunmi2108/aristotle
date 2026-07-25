from typing import Literal

from pydantic import BaseModel, Field

ExecStatus = Literal["ok", "error", "timeout"]


class ExecRequest(BaseModel):
    command: str = Field(min_length=1, max_length=100_000)
    timeout_seconds: float | None = Field(default=None, ge=1, le=1800)


class ExecResult(BaseModel):
    status: ExecStatus
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    duration_ms: int


class FileNode(BaseModel):
    name: str
    path: str
    type: Literal["file", "dir"]
    size: int
    mtime: float


class ListResponse(BaseModel):
    path: str
    entries: list[FileNode]


class PathRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4096)


class MoveRequest(BaseModel):
    src: str = Field(min_length=1, max_length=4096)
    dst: str = Field(min_length=1, max_length=4096)


class OkResponse(BaseModel):
    ok: bool = True


class WriteResponse(BaseModel):
    ok: bool = True
    path: str
    size: int
