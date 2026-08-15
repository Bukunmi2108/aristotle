from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from functools import cached_property
from time import perf_counter
from typing import TYPE_CHECKING, Any

from pydantic_ai.models import Model, ModelRequestParameters, StreamedResponse
from pydantic_ai.profiles import ModelProfile
from pydantic_ai.providers import Provider
from pydantic_ai.tools import RunContext

from app.config import ApiSettings
from app.model_health import mark_provider_unavailable

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelMessage, ModelResponse
    from pydantic_ai.settings import ModelSettings


logger = logging.getLogger(__name__)
_current_trace: ContextVar[ModelTrace | None] = ContextVar(
    "aristotle_model_trace",
    default=None,
)


@dataclass(frozen=True)
class ModelProviderInfo:
    provider: str
    model: str
    url: str


@dataclass
class ModelFailure:
    provider: str
    model: str
    error_type: str
    message: str
    elapsed_ms: int


@dataclass
class ModelTrace:
    primary: ModelProviderInfo
    fallback: ModelProviderInfo | None
    selected: ModelProviderInfo | None = None
    selected_latency_ms: int | None = None
    failures: list[ModelFailure] = field(default_factory=list)

    @property
    def fallback_reason(self) -> str | None:
        if not self.failures:
            return None
        latest = self.failures[-1]
        return f"{latest.error_type}: {latest.message}"

    def record_selected(self, info: ModelProviderInfo, elapsed_ms: int) -> None:
        if self.selected is not None:
            return
        self.selected = info
        self.selected_latency_ms = elapsed_ms
        logger.info(
            "model selected provider=%s model=%s url=%s latency_ms=%s",
            info.provider,
            info.model,
            info.url,
            elapsed_ms,
        )

    def record_failure(
        self,
        info: ModelProviderInfo,
        exc: Exception,
        elapsed_ms: int,
    ) -> None:
        failure = ModelFailure(
            provider=info.provider,
            model=info.model,
            error_type=type(exc).__name__,
            message=str(exc),
            elapsed_ms=elapsed_ms,
        )
        self.failures.append(failure)
        if failure.provider == "primary":
            mark_provider_unavailable("primary", self.fallback_reason or failure.message)
        logger.warning(
            "model provider failed provider=%s model=%s latency_ms=%s error_type=%s error=%s",
            failure.provider,
            failure.model,
            failure.elapsed_ms,
            failure.error_type,
            failure.message,
        )


class TracedModel(Model[Any]):
    def __init__(self, model: Model[Any], info: ModelProviderInfo):
        super().__init__()
        self._model = model
        self.info = info

    async def __aenter__(self) -> "TracedModel":
        await self._model.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> bool | None:
        return await self._model.__aexit__(exc_type, exc_val, exc_tb)

    @property
    def provider(self) -> Provider[Any] | None:
        return self._model.provider

    @property
    def model_name(self) -> str:
        return self._model.model_name

    @property
    def system(self) -> str:
        return self._model.system

    @property
    def base_url(self) -> str | None:
        return self._model.base_url

    @cached_property
    def profile(self) -> ModelProfile:
        return self._model.profile

    async def request(
        self,
        messages: list["ModelMessage"],
        model_settings: "ModelSettings | None",
        model_request_parameters: ModelRequestParameters,
    ) -> "ModelResponse":
        started = perf_counter()
        try:
            response = await self._model.request(
                messages,
                model_settings,
                model_request_parameters,
            )
        except Exception as exc:
            self._record_failure(exc, started)
            raise

        self._record_selected(started)
        return response

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list["ModelMessage"],
        model_settings: "ModelSettings | None",
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,
    ) -> AsyncGenerator[StreamedResponse]:
        started = perf_counter()
        try:
            async with self._model.request_stream(
                messages,
                model_settings,
                model_request_parameters,
                run_context,
            ) as response:
                self._record_selected(started)
                yield response
        except Exception as exc:
            self._record_failure(exc, started)
            raise

    def prepare_request(
        self,
        model_settings: "ModelSettings | None",
        model_request_parameters: ModelRequestParameters,
    ) -> tuple["ModelSettings | None", ModelRequestParameters]:
        return self._model.prepare_request(model_settings, model_request_parameters)

    def prepare_messages(self, messages: list["ModelMessage"]) -> list["ModelMessage"]:
        return self._model.prepare_messages(messages)

    def customize_request_parameters(
        self,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelRequestParameters:
        return self._model.customize_request_parameters(model_request_parameters)

    def _record_selected(self, started: float) -> None:
        trace = get_model_trace()
        if trace is not None:
            trace.record_selected(self.info, _elapsed_ms(started))

    def _record_failure(self, exc: Exception, started: float) -> None:
        trace = get_model_trace()
        if trace is not None:
            trace.record_failure(self.info, exc, _elapsed_ms(started))


def start_model_trace(settings: ApiSettings) -> tuple[ModelTrace, Token[ModelTrace | None]]:
    trace = ModelTrace(
        primary=ModelProviderInfo(
            provider="primary",
            model=settings.primary_model_name,
            url=settings.primary_model_base_url,
        ),
        fallback=ModelProviderInfo(
            provider="fallback",
            model=settings.fallback_model_name,
            url=settings.fallback_model_base_url,
        )
        if settings.model_fallback_enabled
        else None,
    )
    return trace, _current_trace.set(trace)


def reset_model_trace(token: Token[ModelTrace | None]) -> None:
    _current_trace.reset(token)


def get_model_trace() -> ModelTrace | None:
    return _current_trace.get()


def _elapsed_ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)
