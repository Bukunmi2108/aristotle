from typing import Literal
from pydantic import BaseModel, Field, HttpUrl, field_validator


Freshness = Literal["day", "month", "year"]
Category = Literal["general", "news", "science", "code"]


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    max_results: int = Field(default=5, ge=1, le=10)
    language: str = Field(default="en", min_length=2, max_length=12)
    freshness: Freshness | None = None
    domains: list[str] = Field(default_factory=list, max_length=5)
    category: Category = "general"
    engines: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("query cannot be blank")
        return value

    @field_validator("domains")
    @classmethod
    def normalize_domains(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            domain = value.strip().lower()
            if not domain:
                continue
            domain = domain.removeprefix("https://").removeprefix("http://")
            domain = domain.split("/", 1)[0].strip(".")
            if not domain or " " in domain or "." not in domain:
                raise ValueError(f"invalid domain: {value}")
            if domain not in normalized:
                normalized.append(domain)
        return normalized

    @field_validator("engines")
    @classmethod
    def normalize_engines(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            engine = " ".join(value.strip().lower().split())
            if not engine:
                continue
            if any(char in engine for char in {",", "\n", "\r", "\t"}):
                raise ValueError(f"invalid engine: {value}")
            if engine not in normalized:
                normalized.append(engine)
        return normalized


class SearchResult(BaseModel):
    title: str
    url: HttpUrl
    snippet: str = ""
    source: str | None = None
    published_at: str | None = None
    score: float | None = None


class SearchMetadata(BaseModel):
    elapsed_ms: int
    result_count: int
    engines: list[str] = Field(default_factory=list)
    fallback_used: bool = False
    unresponsive_engines: list[str] = Field(default_factory=list)
    attempts: list[dict] = Field(default_factory=list)
    empty_reason: str | None = None


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    metadata: SearchMetadata

    @classmethod
    def from_results(
        cls,
        request: SearchRequest,
        results: list[SearchResult],
        engines: list[str],
        elapsed_ms: int,
        fallback_used: bool = False,
        unresponsive_engines: list[str] | None = None,
        attempts: list[dict] | None = None,
        empty_reason: str | None = None,
    ) -> "SearchResponse":
        return cls(
            query=request.query,
            results=results,
            metadata=SearchMetadata(
                elapsed_ms=elapsed_ms,
                result_count=len(results),
                engines=engines,
                fallback_used=fallback_used,
                unresponsive_engines=unresponsive_engines or [],
                attempts=attempts or [],
                empty_reason=empty_reason,
            ),
        )


class HealthResponse(BaseModel):
    ok: bool
    service: str


class ReadinessResponse(HealthResponse):
    searxng_url: str


class RootResponse(BaseModel):
    service: str
    description: str
    endpoints: dict[str, str]
