from time import perf_counter

import httpx

from app.config import ApiSettings
from app.models import ServiceStatus


class ModelClient:
    def __init__(self, http: httpx.AsyncClient, settings: ApiSettings):
        self.http = http
        self.settings = settings

    async def status(self) -> ServiceStatus:
        started = perf_counter()
        try:
            response = await self.http.get(
                f"{self.settings.model_v1_base_url}/models",
                timeout=20,
            )
            response.raise_for_status()
        except Exception as exc:
            return ServiceStatus(
                ok=False,
                service="model",
                url=self.settings.model_base_url,
                error=str(exc),
            )

        return ServiceStatus(
            ok=True,
            service="model",
            url=self.settings.model_base_url,
            latency_ms=int((perf_counter() - started) * 1000),
        )

    async def is_ready(self) -> bool:
        return (await self.status()).ok
