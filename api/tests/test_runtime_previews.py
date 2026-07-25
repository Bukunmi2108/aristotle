import unittest

from app.agent.capabilities.local_web import FetchUrlResult
from app.agent.runtime import _result_count, _result_preview


class RuntimePreviewTest(unittest.TestCase):
    def test_fetch_url_result_gets_single_fetched_preview(self):
        result = FetchUrlResult(
            url="https://example.com/report",
            title="Example report",
            content="This is useful source text that should be visible as a preview.",
            content_chars=62,
            truncated=False,
            content_type="text/html",
        )

        preview = _result_preview(result)

        self.assertEqual(_result_count(result), 1)
        assert preview is not None
        self.assertEqual(len(preview), 1)
        self.assertEqual(preview[0]["status"], "fetched")
        self.assertEqual(preview[0]["title"], "Example report")
        self.assertIn("useful source text", preview[0]["snippet"])

    def test_failed_fetch_url_result_gets_failed_preview_and_zero_count(self):
        result = FetchUrlResult(
            url="https://example.com/missing",
            title=None,
            content="Fetch failed for https://example.com/missing: 404 Not Found",
            content_chars=61,
            truncated=False,
            content_type=None,
        )

        preview = _result_preview(result)

        self.assertEqual(_result_count(result), 0)
        assert preview is not None
        self.assertEqual(preview[0]["status"], "failed")
        self.assertIn("404 Not Found", preview[0]["snippet"])


if __name__ == "__main__":
    unittest.main()
