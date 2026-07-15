from typing import Any
import httpx
from fastapi import HTTPException, status
from pydantic import HttpUrl, TypeAdapter
from app.models import Category, SearchRequest, SearchResult
from app.url_utils import canonical_url, url_matches_domains


CATEGORY_MAP: dict[Category, str] = {
    "general": "general",
    "news": "news",
    "science": "science",
    "code": "it",
}

HTTP_URL_ADAPTER = TypeAdapter(HttpUrl)


def rewrite_query(request: SearchRequest) -> str:
    if not request.domains:
        return request.query
    site_filter = " OR ".join(f"site:{domain}" for domain in request.domains)
    if len(request.domains) == 1:
        return f"{request.query} {site_filter}"
    return f"{request.query} ({site_filter})"


def searxng_params(request: SearchRequest) -> dict[str, str]:
    params = {
        "q": rewrite_query(request),
        "format": "json",
        "language": request.language,
        "safesearch": "1",
        "categories": CATEGORY_MAP[request.category],
    }
    if request.freshness:
        params["time_range"] = request.freshness
    if request.engines:
        params["engines"] = ",".join(request.engines)
    return params


class SearxngResult:
    def __init__(self, raw: dict[str, Any]):
        self.raw = raw

    @property
    def title(self) -> str:
        return self._string("title")

    @property
    def canonical_url(self) -> str | None:
        return canonical_url(self._string("url"))

    @property
    def engines(self) -> list[str]:
        engines = self.raw.get("engines")
        if isinstance(engines, list):
            return [str(engine) for engine in engines if engine]

        engine = self.raw.get("engine")
        return [str(engine)] if engine else []

    def to_search_result(self) -> SearchResult | None:
        url = self.canonical_url
        title = self.title
        if not title or not url:
            return None

        engines = self.engines
        return SearchResult(
            title=title,
            url=HTTP_URL_ADAPTER.validate_python(url),
            snippet=self._string("content", "snippet", "description"),
            source=engines[0] if engines else None,
            published_at=self._optional_string("publishedDate", "published_at"),
            score=self._score(),
        )

    def _string(self, *keys: str) -> str:
        for key in keys:
            value = self.raw.get(key)
            if value:
                return str(value).strip()
        return ""

    def _optional_string(self, *keys: str) -> str | None:
        value = self._string(*keys)
        return value or None

    def _score(self) -> float | None:
        score = self.raw.get("score")
        if score is None:
            return None
        try:
            return float(score)
        except (TypeError, ValueError):
            return None


class SearxngPayload:
    def __init__(self, raw: dict[str, Any]):
        self.raw = raw

    @property
    def results(self) -> list[SearxngResult]:
        raw_results = self.raw.get("results")
        if not isinstance(raw_results, list):
            return []
        return [
            SearxngResult(raw_result)
            for raw_result in raw_results
            if isinstance(raw_result, dict)
        ]

    @property
    def unresponsive_engines(self) -> list[str]:
        raw_engines = self.raw.get("unresponsive_engines")
        if not isinstance(raw_engines, list):
            return []

        engines: list[str] = []
        for raw_engine in raw_engines:
            if isinstance(raw_engine, str):
                engine = raw_engine
            elif isinstance(raw_engine, (list, tuple)) and raw_engine:
                engine = str(raw_engine[0])
            else:
                continue
            if engine and engine not in engines:
                engines.append(engine)
        return engines

    def normalize(self, request: SearchRequest) -> tuple[list[SearchResult], list[str]]:
        normalized_results: list[SearchResult] = []
        seen_urls: set[str] = set()
        engines: set[str] = set()

        for raw_result in self.results:
            engines.update(raw_result.engines)

            canonical = raw_result.canonical_url
            if (
                canonical is None
                or canonical in seen_urls
                or not url_matches_domains(canonical, request.domains)
            ):
                continue

            normalized = raw_result.to_search_result()
            if normalized is None:
                continue

            seen_urls.add(canonical)
            normalized_results.append(normalized)
            if len(normalized_results) >= request.max_results:
                break

        return normalized_results, sorted(engines)


class SearxngClient:
    def __init__(self, http: httpx.AsyncClient, base_url: str):
        self.http = http
        self.base_url = base_url.rstrip("/")

    async def search(self, params: dict[str, str]) -> SearxngPayload:
        try:
            response = await self.http.get(
                f"{self.base_url}/search",
                params=params,
                headers={"X-Real-IP": "127.0.0.1"},
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="search backend timed out",
            ) from exc
        except httpx.ConnectError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="search backend is unavailable",
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"search backend returned HTTP {exc.response.status_code}",
            ) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="search backend request failed",
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="search backend returned invalid JSON",
            ) from exc

        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="search backend returned unexpected JSON",
            )
        return SearxngPayload(payload)
