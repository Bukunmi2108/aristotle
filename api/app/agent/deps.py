import httpx
from app.config import ApiSettings
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
    ):
        self.search_client = search_client
        self.http_client = http_client
        self.events = events
        self.settings = settings
        self.max_search_results = max_search_results
        self.web_tools_enabled = web_tools_enabled
