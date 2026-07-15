import asyncio
import unittest
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch

from app.main import app, services
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
        app.state.model_client = model_client
        app.state.search_client = search_client

        started = perf_counter()
        await services()
        elapsed = perf_counter() - started

        # Sequential awaits would take >= 0.10s; concurrent should be close to 0.05s.
        self.assertLess(elapsed, 0.09)
        assert model_client.started is not None
        assert search_client.started is not None
        assert model_client.finished is not None
        assert search_client.finished is not None
        # The two status() calls must overlap in time.
        self.assertLess(model_client.started, search_client.finished)
        self.assertLess(search_client.started, model_client.finished)

    async def test_response_includes_wake_config(self):
        app.state.model_client = FakeClient("model", 0)
        app.state.search_client = FakeClient("search", 0)
        fake_settings = SimpleNamespace(
            wake_poll_interval_seconds=7.0, wake_timeout_seconds=42.0
        )

        with patch("app.main.SETTINGS", fake_settings):
            response = await services()

        self.assertEqual(response.poll_interval_seconds, 7.0)
        self.assertEqual(response.wake_timeout_seconds, 42.0)


if __name__ == "__main__":
    unittest.main()
