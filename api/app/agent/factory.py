from pathlib import Path
from typing import cast

from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.openai import OpenAIProvider
from openai import AsyncOpenAI

from app.agent.capabilities import CUSTOM_CAPABILITY_TYPES
from app.agent.deps import AgentDeps
from app.agent.model_trace import ModelProviderInfo, TracedModel
from app.config import ApiSettings


AGENT_SPEC_PATH = Path(__file__).with_name("specs") / "aristotle.yaml"

LLAMA_CPP_OPENAI_PROFILE = cast(
    OpenAIModelProfile,
    {
        "supports_tools": True,
        "supports_thinking": True,
        "openai_chat_thinking_field": "reasoning_content",
        "openai_chat_supports_max_completion_tokens": False,
        "openai_supports_strict_tool_definition": False,
    },
)

MODELSCOPE_OPENAI_PROFILE = cast(
    OpenAIModelProfile,
    {
        "supports_tools": True,
        "supports_thinking": True,
        "openai_chat_thinking_field": "reasoning_content",
        "openai_supports_strict_tool_definition": False,
    },
)


def build_agent(
    settings: ApiSettings,
) -> Agent[AgentDeps, str]:
    return Agent.from_file(
        AGENT_SPEC_PATH,
        model=build_model(settings),
        deps_type=AgentDeps,
        custom_capability_types=CUSTOM_CAPABILITY_TYPES,
        tool_timeout=settings.search_request_timeout_seconds
        + settings.wake_timeout_seconds,
    )


def build_model(settings: ApiSettings) -> OpenAIChatModel | FallbackModel | TracedModel:
    fallback_model = TracedModel(
        _build_openai_model(
            model_name=settings.fallback_model_name,
            base_url=settings.fallback_model_base_url,
            api_key=settings.fallback_model_api_key,
            profile=LLAMA_CPP_OPENAI_PROFILE,
        ),
        ModelProviderInfo(
            provider="fallback",
            model=settings.fallback_model_name,
            url=settings.fallback_model_base_url,
        ),
    )

    if not settings.primary_model_api_key and settings.model_fallback_enabled:
        return fallback_model
    if not settings.primary_model_api_key:
        raise RuntimeError(
            "PRIMARY_MODEL_API_KEY, MODELSCOPE_API_KEY, or MODELSCOPE_SDK_TOKEN "
            "is required when MODEL_FALLBACK_ENABLED=false."
        )

    primary_model = TracedModel(
        _build_openai_model(
            model_name=settings.primary_model_name,
            base_url=settings.primary_model_base_url,
            api_key=settings.primary_model_api_key,
            profile=MODELSCOPE_OPENAI_PROFILE,
        ),
        ModelProviderInfo(
            provider="primary",
            model=settings.primary_model_name,
            url=settings.primary_model_base_url,
        ),
    )

    if not settings.model_fallback_enabled:
        return primary_model

    return FallbackModel(
        primary_model,
        fallback_model,
        fallback_on=_should_fallback_on_model_error,
    )


def _build_openai_model(
    *,
    model_name: str,
    base_url: str,
    api_key: str,
    profile: OpenAIModelProfile,
) -> OpenAIChatModel:
    return OpenAIChatModel(
        model_name,
        provider=OpenAIProvider(
            openai_client=AsyncOpenAI(
                base_url=base_url,
                api_key=api_key,
                max_retries=0,
            ),
        ),
        profile=profile,
    )


def _should_fallback_on_model_error(exc: Exception) -> bool:
    if isinstance(exc, ModelHTTPError):
        body = str(exc.body or "").lower()
        quota_or_limit = any(
            marker in body
            for marker in ("insufficient_quota", "quota", "rate limit", "too many")
        )
        if quota_or_limit:
            return True
        return exc.status_code in {408, 429, 500, 502, 503, 504}

    return isinstance(exc, ModelAPIError)
