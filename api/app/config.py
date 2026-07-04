import os
from dataclasses import dataclass
from urllib.parse import urlparse


SERVICE_NAME = "aristotle-api"
DEFAULT_FALLBACK_MODEL_BASE_URL = "https://bukunmi2108-aristotle-model.hf.space"
DEFAULT_FALLBACK_MODEL_NAME = "/models/NVIDIA-Nemotron3-Nano-4B-Q4_K_M.gguf"
DEFAULT_PRIMARY_MODEL_BASE_URL = "https://api-inference.modelscope.ai/v1"
DEFAULT_PRIMARY_MODEL_NAME = "Qwen/Qwen3-235B-A22B-Instruct-2507"


@dataclass(frozen=True)
class ApiSettings:
    port: int
    cors_allow_origins: list[str]
    primary_model_base_url: str
    primary_model_name: str
    primary_model_api_key: str | None
    fallback_model_base_url: str
    fallback_model_name: str
    fallback_model_api_key: str
    model_fallback_enabled: bool
    search_base_url: str
    wake_timeout_seconds: float
    wake_poll_interval_seconds: float
    model_request_timeout_seconds: float
    search_request_timeout_seconds: float
    web_fetch_timeout_seconds: float
    agent_temperature: float

    @classmethod
    def from_env(cls) -> "ApiSettings":
        legacy_model_base_url = os.getenv(
            "ARISTOTLE_MODEL_BASE_URL",
            DEFAULT_FALLBACK_MODEL_BASE_URL,
        ).rstrip("/")
        return cls(
            port=int(os.getenv("PORT", "7860")),
            cors_allow_origins=_split_csv(os.getenv("CORS_ALLOW_ORIGINS", "*")),
            primary_model_base_url=_as_v1_base_url(
                os.getenv("PRIMARY_MODEL_BASE_URL", DEFAULT_PRIMARY_MODEL_BASE_URL)
            ),
            primary_model_name=os.getenv(
                "PRIMARY_MODEL_NAME",
                DEFAULT_PRIMARY_MODEL_NAME,
            ),
            primary_model_api_key=_optional_env("PRIMARY_MODEL_API_KEY")
            or _optional_env("MODELSCOPE_API_KEY")
            or _optional_env("MODELSCOPE_SDK_TOKEN"),
            fallback_model_base_url=_as_v1_base_url(
                os.getenv("FALLBACK_MODEL_BASE_URL", legacy_model_base_url)
            ),
            fallback_model_name=os.getenv(
                "FALLBACK_MODEL_NAME",
                os.getenv("ARISTOTLE_MODEL_NAME", DEFAULT_FALLBACK_MODEL_NAME),
            ),
            fallback_model_api_key=os.getenv("FALLBACK_MODEL_API_KEY", "unused"),
            model_fallback_enabled=_bool_env("MODEL_FALLBACK_ENABLED", True),
            search_base_url=os.getenv(
                "ARISTOTLE_SEARCH_BASE_URL",
                "https://bukunmi2108-aristotle-search.hf.space",
            ).rstrip("/"),
            wake_timeout_seconds=float(os.getenv("WAKE_TIMEOUT_SECONDS", "180")),
            wake_poll_interval_seconds=float(
                os.getenv("WAKE_POLL_INTERVAL_SECONDS", "3")
            ),
            model_request_timeout_seconds=float(
                os.getenv("MODEL_REQUEST_TIMEOUT_SECONDS", "180")
            ),
            search_request_timeout_seconds=float(
                os.getenv("SEARCH_REQUEST_TIMEOUT_SECONDS", "30")
            ),
            web_fetch_timeout_seconds=float(
                os.getenv("WEB_FETCH_TIMEOUT_SECONDS", "20")
            ),
            agent_temperature=float(os.getenv("AGENT_TEMPERATURE", "0.2")),
        )

    @property
    def model_base_url(self) -> str:
        return self.primary_model_base_url

    @property
    def model_name(self) -> str:
        return self.primary_model_name

    @property
    def model_v1_base_url(self) -> str:
        return self.primary_model_base_url


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    return value


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _as_v1_base_url(value: str) -> str:
    base_url = value.rstrip("/")
    parsed = urlparse(base_url)
    if parsed.path.rstrip("/").endswith("/v1"):
        return base_url
    return f"{base_url}/v1"


SETTINGS = ApiSettings.from_env()
