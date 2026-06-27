from time import perf_counter

import httpx

from app.config import ApiSettings
from app.models import SearchResponse, SearchToolRequest, ServiceStatus


class SearchClient:
    def __init__(self, http: httpx.AsyncClient, settings: ApiSettings):
        self.http = http
        self.settings = settings

    async def status(self) -> ServiceStatus:
        started = perf_counter()
        try:
            response = await self.http.get(
                f"{self.settings.search_base_url}/readyz",
                timeout=20,
            )
            response.raise_for_status()
        except Exception as exc:
            return ServiceStatus(
                ok=False,
                service="search",
                url=self.settings.search_base_url,
                error=str(exc),
            )

        return ServiceStatus(
            ok=True,
            service="search",
            url=self.settings.search_base_url,
            latency_ms=int((perf_counter() - started) * 1000),
        )

    async def is_ready(self) -> bool:
        return (await self.status()).ok

    async def search(self, request: SearchToolRequest) -> SearchResponse:
        response = await self.http.post(
            f"{self.settings.search_base_url}/search",
            json=request.model_dump(),
            timeout=self.settings.search_request_timeout_seconds,
        )
        response.raise_for_status()
        return SearchResponse.model_validate(response.json())
