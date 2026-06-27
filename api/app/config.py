import os
from dataclasses import dataclass


SERVICE_NAME = "aristotle-api"


@dataclass(frozen=True)
class ApiSettings:
    port: int
    cors_allow_origins: list[str]
    model_base_url: str
    model_name: str
    search_base_url: str
    wake_timeout_seconds: float
    wake_poll_interval_seconds: float
    model_request_timeout_seconds: float
    search_request_timeout_seconds: float
    web_fetch_timeout_seconds: float
    agent_temperature: float

    @classmethod
    def from_env(cls) -> "ApiSettings":
        return cls(
            port=int(os.getenv("PORT", "7860")),
            cors_allow_origins=_split_csv(os.getenv("CORS_ALLOW_ORIGINS", "*")),
            model_base_url=os.getenv(
                "ARISTOTLE_MODEL_BASE_URL",
                "https://bukunmi2108-aristotle-model.hf.space",
            ).rstrip("/"),
            model_name=os.getenv(
                "ARISTOTLE_MODEL_NAME", "/models/NVIDIA-Nemotron3-Nano-4B-Q4_K_M.gguf"
            ),
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
    def model_v1_base_url(self) -> str:
        return f"{self.model_base_url}/v1"


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


SETTINGS = ApiSettings.from_env()
