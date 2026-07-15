import unittest

from app.agent.capabilities.local_web import FetchUrlResult
from app.agent.runtime import _result_artifacts, _result_count, _result_output, _result_preview
from app.models import ArtifactRecord, SandboxRunResult


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

    def test_result_artifacts_returns_none_for_non_sandbox_content(self):
        self.assertIsNone(_result_artifacts("just a string"))

    def test_result_artifacts_returns_none_when_empty(self):
        result = SandboxRunResult(
            status="ok", stdout="", stderr="", exit_code=0,
            timed_out=False, duration_ms=1, artifacts=[],
        )
        self.assertIsNone(_result_artifacts(result))

    def test_result_artifacts_maps_artifact_records(self):
        result = SandboxRunResult(
            status="ok", stdout="", stderr="", exit_code=0,
            timed_out=False, duration_ms=1,
            artifacts=[
                ArtifactRecord(
                    id="artifact_1", sandbox_run_id="sbx_1",
                    filename="chart.png", mime_type="image/png", size_bytes=100,
                )
            ],
        )
        artifacts = _result_artifacts(result)
        assert artifacts is not None
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(
            artifacts[0], {
                "id": "artifact_1", "filename": "chart.png",
                "mime_type": "image/png", "size_bytes": 100,
            },
        )
        self.assertNotIn("storage_path", artifacts[0])
        self.assertNotIn("sandbox_run_id", artifacts[0])

    def test_result_output_returns_none_for_non_sandbox_content(self):
        self.assertIsNone(_result_output(42))

    def test_result_output_includes_status(self):
        result = SandboxRunResult(
            status="timeout", stdout="partial", stderr="Execution timed out.",
            exit_code=-1, timed_out=True, duration_ms=10000, artifacts=[],
        )
        output = _result_output(result)
        self.assertEqual(
            output, {
                "status": "timeout", "stdout": "partial",
                "stderr": "Execution timed out.", "exit_code": -1, "timed_out": True,
            },
        )


if __name__ == "__main__":
    unittest.main()
