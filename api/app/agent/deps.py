import httpx
from app.config import ApiSettings
from app.db import PersistenceStore
from app.events import EventSender
from app.services.search import SearchClient


class AgentDeps:
    def __init__(
        self,
        search_client: SearchClient,
        http_client: httpx.AsyncClient,
        events: EventSender,
        settings: ApiSettings,
        max_search_results: int,
        web_tools_enabled: bool,
        document_store: PersistenceStore | None = None,
        file_ids: list[str] | None = None,
    ):
        self.search_client = search_client
        self.http_client = http_client
        self.events = events
        self.settings = settings
        self.max_search_results = max_search_results
        self.web_tools_enabled = web_tools_enabled
        self.document_store = document_store
        self.file_ids = file_ids or []
        self.document_tools_enabled = document_store is not None and bool(self.file_ids)
