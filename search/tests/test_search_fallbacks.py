import unittest

from app.main import _build_search_attempts, search
from app.models import SearchRequest
from app.searxng import SearxngPayload, searxng_params


class FakeSearxngClient:
    def __init__(self, payloads: list[dict]):
        self.payloads = list(payloads)
        self.params: list[dict[str, str]] = []

    async def search(self, params: dict[str, str]) -> SearxngPayload:
        self.params.append(params)
        return SearxngPayload(self.payloads.pop(0))


class SearchFallbacksTest(unittest.IsolatedAsyncioTestCase):
    def test_params_include_request_level_engines(self):
        params = searxng_params(
            SearchRequest(query="python asyncio", engines=["bing", "presearch"])
        )

        self.assertEqual(params["engines"], "bing,presearch")

    def test_general_search_starts_with_profile_then_default_fallback(self):
        attempts = _build_search_attempts(SearchRequest(query="python asyncio"))

        self.assertEqual(attempts[0].reason, "general_profile")
        self.assertEqual(attempts[0].request.engines, ["bing", "presearch"])
        self.assertIn("default_engines", [attempt.reason for attempt in attempts])

    def test_domain_search_does_not_force_profile_engines(self):
        attempts = _build_search_attempts(
            SearchRequest(query="release notes", domains=["example.com"])
        )

        self.assertEqual(attempts[0].reason, "domain_default_engines")
        self.assertEqual(attempts[0].request.engines, [])

    async def test_empty_profile_retries_and_returns_attempt_metadata(self):
        fake_client = FakeSearxngClient(
            [
                {
                    "results": [],
                    "unresponsive_engines": [["brave", "too many requests"]],
                },
                {
                    "results": [
                        {
                            "title": "Asyncio docs",
                            "url": "https://docs.python.org/3/library/asyncio.html",
                            "content": "Asyncio documentation.",
                            "engine": "bing",
                        }
                    ]
                },
            ]
        )

        response = await search(SearchRequest(query="python asyncio"), fake_client)

        self.assertEqual(len(response.results), 1)
        self.assertTrue(response.metadata.fallback_used)
        self.assertEqual(response.metadata.unresponsive_engines, ["brave"])
        self.assertEqual(
            [attempt["reason"] for attempt in response.metadata.attempts],
            ["general_profile", "general_profile_relaxed_language"],
        )


if __name__ == "__main__":
    unittest.main()
