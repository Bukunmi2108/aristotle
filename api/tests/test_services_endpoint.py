import asyncio
import unittest
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.main import app, readyz, services
from app.models import ServiceName, ServiceStatus


class FakeClient:
    def __init__(self, service: ServiceName, delay: float):
        self.service = service
        self.delay = delay
        self.started: float | None = None
        self.finished: float | None = None

    async def status(self) -> ServiceStatus:
        self.started = perf_counter()
        await asyncio.sleep(self.delay)
        self.finished = perf_counter()
        return ServiceStatus(ok=True, service=self.service, url="http://fake")


class ServicesEndpointTest(unittest.IsolatedAsyncioTestCase):
    async def test_status_checks_run_concurrently(self):
        model_client = FakeClient("model", 0.05)
        search_client = FakeClient("search", 0.05)
        sandbox_client = FakeClient("sandbox", 0.05)
        app.state.model_client = model_client
        app.state.search_client = search_client
        app.state.sandbox_client = sandbox_client

        started = perf_counter()
        with patch("app.main.SETTINGS", _settings(workspace_enabled=True)):
            await services()
        elapsed = perf_counter() - started

        # Sequential awaits would take >= 0.10s; concurrent should be close to 0.05s.
        self.assertLess(elapsed, 0.09)
        assert model_client.started is not None
        assert search_client.started is not None
        assert model_client.finished is not None
        assert search_client.finished is not None
        assert sandbox_client.started is not None
        assert sandbox_client.finished is not None
        # The two status() calls must overlap in time.
        self.assertLess(model_client.started, search_client.finished)
        self.assertLess(search_client.started, model_client.finished)
        self.assertLess(model_client.started, sandbox_client.finished)
        self.assertLess(sandbox_client.started, model_client.finished)

    async def test_response_includes_wake_config(self):
        app.state.model_client = FakeClient("model", 0)
        app.state.search_client = FakeClient("search", 0)
        app.state.sandbox_client = FakeClient("sandbox", 0)
        fake_settings = SimpleNamespace(
            workspace_enabled=True,
            wake_poll_interval_seconds=7.0,
            wake_timeout_seconds=42.0,
        )

        with patch("app.main.SETTINGS", fake_settings):
            response = await services()

        self.assertEqual(response.poll_interval_seconds, 7.0)
        self.assertEqual(response.wake_timeout_seconds, 42.0)
        self.assertIsNotNone(response.sandbox)

    async def test_workspace_enabled_and_sandbox_unavailable_is_not_ready(self):
        app.state.model_client = FakeClient("model", 0)
        app.state.search_client = FakeClient("search", 0)
        app.state.sandbox_client = FakeClient("sandbox", 0)
        app.state.sandbox_client.status = lambda: _status(
            "sandbox", ok=False, error="Name resolution failed."
        )

        with patch("app.main.SETTINGS", _settings(workspace_enabled=True)):
            with self.assertRaises(HTTPException) as raised:
                await readyz()
        self.assertEqual(raised.exception.status_code, 503)

    async def test_workspace_disabled_omits_sandbox_readiness(self):
        app.state.model_client = FakeClient("model", 0)
        app.state.search_client = FakeClient("search", 0)
        app.state.sandbox_client = None

        with patch("app.main.SETTINGS", _settings(workspace_enabled=False)):
            response = await readyz()

        self.assertTrue(response.ok)
        self.assertIsNone(response.services.sandbox)


async def _status(
    service: ServiceName, *, ok: bool, error: str | None = None
) -> ServiceStatus:
    return ServiceStatus(
        ok=ok,
        service=service,
        url="http://fake",
        error=error,
    )


def _settings(*, workspace_enabled: bool) -> SimpleNamespace:
    return SimpleNamespace(
        workspace_enabled=workspace_enabled,
        wake_poll_interval_seconds=7.0,
        wake_timeout_seconds=42.0,
    )


if __name__ == "__main__":
    unittest.main()
