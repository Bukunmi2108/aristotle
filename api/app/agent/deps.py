import httpx

from app.config import ApiSettings
from app.db import PersistenceStore
from app.events import EventSender
from app.services.sandbox_client import Workspace
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
        workspace: Workspace | None = None,
        conversation_id: str | None = None,
        run_id: str | None = None,
        message_id: str | None = None,
        execution_pass: int = 0,
    ):
        self._search_client = search_client
        self._http_client = http_client
        self._events = events
        self._settings = settings
        self.max_search_results = max_search_results
        self.web_tools_enabled = web_tools_enabled
        self._document_store = document_store
        self.file_ids = file_ids or []
        self.document_tools_enabled = document_store is not None and bool(self.file_ids)
        self._workspace = workspace
        self.workspace_tools_enabled = workspace is not None
        self.conversation_id = conversation_id
        self.run_id = run_id
        self.message_id = message_id
        self.execution_pass = execution_pass

    @property
    def search_client(self):
        if self._search_client is not None:
            return self._search_client
        return self._services().search_client

    @property
    def http_client(self):
        if self._http_client is not None:
            return self._http_client
        return self._services().http

    @property
    def events(self):
        if self._events is not None:
            return self._events
        from app.events import EventSender

        self._events = EventSender(
            None,
            conversation_id=self.conversation_id or "unknown",
            run_id=self.run_id,
            message_id=self.message_id,
            store=self._services().store,
        )
        return self._events

    @property
    def settings(self):
        if self._settings is not None:
            return self._settings
        return self._services().settings

    @property
    def document_store(self):
        if self._document_store is not None:
            return self._document_store
        return self._services().store

    @property
    def workspace(self):
        if self._workspace is not None:
            return self._workspace
        if not self.workspace_tools_enabled or self.conversation_id is None:
            return None
        from app.services.sandbox_client import Workspace

        sandbox = self._services().sandbox_client
        if sandbox is None:
            return None
        self._workspace = Workspace(sandbox, self.conversation_id)
        return self._workspace

    def __getstate__(self):
        return {
            "max_search_results": self.max_search_results,
            "web_tools_enabled": self.web_tools_enabled,
            "file_ids": self.file_ids,
            "document_tools_enabled": self.document_tools_enabled,
            "workspace_tools_enabled": self.workspace_tools_enabled,
            "conversation_id": self.conversation_id,
            "run_id": self.run_id,
            "message_id": self.message_id,
            "execution_pass": self.execution_pass,
        }

    def __setstate__(self, state):
        self.__dict__.update(state)
        self._search_client = None
        self._http_client = None
        self._events = None
        self._settings = None
        self._document_store = None
        self._workspace = None

    @staticmethod
    def _services():
        from app.runtime_services import get_runtime_services

        return get_runtime_services()
