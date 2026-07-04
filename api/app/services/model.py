from time import perf_counter

import httpx

from app.config import ApiSettings
from app.model_health import get_provider_unavailable
from app.models import ServiceStatus


class ModelClient:
    def __init__(self, http: httpx.AsyncClient, settings: ApiSettings):
        self.http = http
        self.settings = settings

    async def status(self) -> ServiceStatus:
        primary_unavailable = get_provider_unavailable("primary")
        primary = None
        if primary_unavailable is None:
            primary = await self._provider_status(
                base_url=self.settings.primary_model_base_url,
                model_name=self.settings.primary_model_name,
                api_key=self.settings.primary_model_api_key,
            )
            if primary.ok:
                return primary

        if self.settings.model_fallback_enabled:
            fallback = await self._provider_status(
                base_url=self.settings.fallback_model_base_url,
                model_name=self.settings.fallback_model_name,
                api_key=self.settings.fallback_model_api_key,
            )
            if fallback.ok:
                return fallback

        return ServiceStatus(
            ok=False,
            service="model",
            url=self.settings.primary_model_base_url,
            error=primary_unavailable.reason
            if primary_unavailable is not None
            else primary.error
            if primary is not None
            else "Primary model is unavailable.",
        )

    async def is_ready(self) -> bool:
        return (await self.status()).ok

    async def _provider_status(
        self,
        *,
        base_url: str,
        model_name: str,
        api_key: str | None,
    ) -> ServiceStatus:
        started = perf_counter()

        if not api_key:
            return ServiceStatus(
                ok=False,
                service="model",
                url=base_url,
                error="API key is not configured.",
            )

        try:
            response = await self.http.get(
                f"{base_url}/models",
                timeout=20,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            response.raise_for_status()
            self._verify_model_available(response.json(), model_name)
        except Exception as exc:
            return ServiceStatus(
                ok=False,
                service="model",
                url=base_url,
                error=str(exc),
            )

        return ServiceStatus(
            ok=True,
            service="model",
            url=base_url,
            latency_ms=int((perf_counter() - started) * 1000),
        )

    def _verify_model_available(self, payload: object, model_name: str) -> None:
        if not isinstance(payload, dict):
            return

        models = payload.get("data")
        if not isinstance(models, list):
            return

        ids = {
            model.get("id")
            for model in models
            if isinstance(model, dict) and isinstance(model.get("id"), str)
        }
        if ids and model_name not in ids:
            raise ValueError(f"Model {model_name!r} is not listed by provider.")
