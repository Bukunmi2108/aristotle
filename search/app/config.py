import os
from dataclasses import dataclass
import httpx

SERVICE_NAME = "aristotle-search"

@dataclass(frozen=True)
class SearchServiceSettings:
    searxng_internal_url: str
    search_timeout_seconds: float
    searxng_timeout_seconds: float

    @classmethod
    def from_env(cls) -> "SearchServiceSettings":
        return cls(
            searxng_internal_url=os.getenv("SEARXNG_INTERNAL_URL", "http://127.0.0.1:8080").rstrip("/"),
            search_timeout_seconds=float(os.getenv("SEARCH_TIMEOUT_SECONDS", "15")),
            searxng_timeout_seconds=float(os.getenv("SEARXNG_TIMEOUT_SECONDS", "12")),
        )

    def http_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            timeout=self.search_timeout_seconds,
            connect=5.0,
            read=self.searxng_timeout_seconds,
        )


SETTINGS = SearchServiceSettings.from_env()
