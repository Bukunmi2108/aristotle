from typing import Literal
from pydantic import BaseModel, Field


ServiceName = Literal["model", "search"]
Freshness = Literal["day", "month", "year"]


class RootResponse(BaseModel):
    service: str
    description: str
    endpoints: dict[str, str]


class HealthResponse(BaseModel):
    ok: bool
    service: str


class ServiceStatus(BaseModel):
    ok: bool
    service: ServiceName
    url: str
    model: str | None = None
    latency_ms: int | None = None
    error: str | None = None


class ServicesResponse(BaseModel):
    model: ServiceStatus
    search: ServiceStatus
    poll_interval_seconds: float | None = None
    wake_timeout_seconds: float | None = None

    @property
    def ok(self) -> bool:
        return self.model.ok and self.search.ok


class ReadyResponse(BaseModel):
    ok: bool
    services: ServicesResponse


class RenameConversationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class ChatOptions(BaseModel):
    max_search_results: int = Field(default=5, ge=1, le=10)
    file_ids: list[str] = Field(default_factory=list, max_length=10)


class ChatHistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=12000)


class ClientUserMessage(BaseModel):
    type: Literal["user.message"]
    message: str = Field(min_length=1, max_length=12000)
    conversation_id: str | None = None
    history: list[ChatHistoryMessage] = Field(default_factory=list, max_length=24)
    options: ChatOptions = Field(default_factory=ChatOptions)


class SearchToolRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    max_results: int = Field(default=5, ge=1, le=10)
    freshness: Freshness | None = None
    domains: list[str] = Field(default_factory=list, max_length=5)


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str = ""
    source: str | None = None
    published_at: str | None = None
    score: float | None = None


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    metadata: dict


class FileRecord(BaseModel):
    id: str
    owner_id: str | None = None
    filename: str
    mime_type: str
    size_bytes: int
    storage_path: str
    uploaded_at: str
    parse_status: str
    parse_error: str | None = None


class FileUploadResponse(BaseModel):
    file: FileRecord


class ArtifactRecord(BaseModel):
    """Model/tool-facing artifact reference.

    Deliberately excludes the host `storage_path` — that stays internal to
    the sandbox/db layer and is never serialized back to the LLM. Downloads
    go through `GET /artifacts/{id}`, which re-resolves the path from the DB
    by id rather than trusting anything on this object.
    """

    id: str
    sandbox_run_id: str
    filename: str
    mime_type: str
    size_bytes: int


SandboxRunStatus = Literal["ok", "error", "timeout", "rejected"]


class SandboxRunResult(BaseModel):
    status: SandboxRunStatus
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    duration_ms: int
    artifacts: list[ArtifactRecord] = Field(default_factory=list)
