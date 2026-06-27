from pathlib import Path
from typing import cast

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.openai import OpenAIProvider
from openai import AsyncOpenAI

from app.agent.capabilities import CUSTOM_CAPABILITY_TYPES
from app.agent.deps import AgentDeps
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


def build_agent(
    settings: ApiSettings,
) -> Agent[AgentDeps, str]:
    model = OpenAIChatModel(
        settings.model_name,
        provider=OpenAIProvider(
            openai_client=AsyncOpenAI(
                base_url=settings.model_v1_base_url,
                api_key="unused",
                max_retries=0,
            ),
        ),
        profile=LLAMA_CPP_OPENAI_PROFILE,
    )
    return Agent.from_file(
        AGENT_SPEC_PATH,
        model=model,
        deps_type=AgentDeps,
        custom_capability_types=CUSTOM_CAPABILITY_TYPES,
        tool_timeout=settings.search_request_timeout_seconds
        + settings.wake_timeout_seconds,
    )
