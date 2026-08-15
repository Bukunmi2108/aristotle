from __future__ import annotations

import asyncio
import logging
import signal
import socket
from pathlib import Path

import httpx
from dbos import DBOS, Queue

from app.agent.factory import build_agent
from app.config import SETTINGS
from app.db import close_store, create_store
from app.runtime_services import RuntimeServices, set_runtime_services
from app.services.model import ModelClient
from app.services.sandbox_client import SandboxClient
from app.services.search import SearchClient

logger = logging.getLogger(__name__)
READY_PATH = Path("/tmp/aristotle-worker-ready")
WORKER_ID = socket.gethostname()


async def main() -> None:
    READY_PATH.unlink(missing_ok=True)
    if not SETTINGS.database_url:
        raise RuntimeError("DATABASE_URL is required by the durable worker.")

    DBOS(
        config={
            "name": "aristotle",
            "system_database_url": SETTINGS.database_url,
            "application_version": SETTINGS.dbos_application_version,
            "run_admin_server": False,
        }
    )
    from app.durable.workflow import set_durable_agent

    http = httpx.AsyncClient(follow_redirects=True)
    store = await create_store(SETTINGS)
    if store is None:
        raise RuntimeError("DATABASE_URL is required by the durable worker.")
    model_client = ModelClient(http=http, settings=SETTINGS)
    search_client = SearchClient(http=http, settings=SETTINGS)
    sandbox_client = (
        SandboxClient(http=http, settings=SETTINGS)
        if SETTINGS.workspace_enabled
        else None
    )
    set_runtime_services(
        RuntimeServices(
            http=http,
            settings=SETTINGS,
            model_client=model_client,
            search_client=search_client,
            store=store,
            sandbox_client=sandbox_client,
        )
    )
    set_durable_agent(build_agent(SETTINGS, durable=True))
    Queue(
        "aristotle-agent",
        worker_concurrency=SETTINGS.agent_queue_concurrency,
    )
    DBOS.listen_queues(["aristotle-agent"])
    DBOS.launch()
    await store.heartbeat_worker(
        worker_id=WORKER_ID,
        application_version=SETTINGS.dbos_application_version,
    )
    READY_PATH.touch()
    logger.info("Aristotle durable worker ready")

    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stopped.set)
    heartbeat = asyncio.create_task(_heartbeat(store))
    try:
        await stopped.wait()
    finally:
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)
        await store.remove_worker_heartbeat(WORKER_ID)
        READY_PATH.unlink(missing_ok=True)
        DBOS.destroy(workflow_completion_timeout_sec=15)
        set_runtime_services(None)
        await close_store(store)
        await http.aclose()


async def _heartbeat(store) -> None:
    while True:
        await asyncio.sleep(10)
        await store.heartbeat_worker(
            worker_id=WORKER_ID,
            application_version=SETTINGS.dbos_application_version,
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
