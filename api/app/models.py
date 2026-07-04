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

    @property
    def ok(self) -> bool:
        return self.model.ok and self.search.ok


class ReadyResponse(BaseModel):
    ok: bool
    services: ServicesResponse


class RenameConversationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class ChatOptions(BaseModel):
    use_search: bool = True
    max_search_results: int = Field(default=5, ge=1, le=10)


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
