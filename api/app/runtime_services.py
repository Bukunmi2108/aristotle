from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.config import ApiSettings
from app.db import PersistenceStore
from app.services.model import ModelClient
from app.services.sandbox_client import SandboxClient
from app.services.search import SearchClient


@dataclass
class RuntimeServices:
    http: httpx.AsyncClient
    settings: ApiSettings
    model_client: ModelClient
    search_client: SearchClient
    store: PersistenceStore
    sandbox_client: SandboxClient | None


_services: RuntimeServices | None = None


def set_runtime_services(services: RuntimeServices | None) -> None:
    global _services
    _services = services


def get_runtime_services() -> RuntimeServices:
    if _services is None:
        raise RuntimeError("Agent runtime services are not initialized.")
    return _services
