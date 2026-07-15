import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from app.main import app, download_artifact


class FakeStore:
    def __init__(self, artifacts: dict[str, dict]):
        self.artifacts = artifacts

    async def get_artifact(self, artifact_id: str):
        return self.artifacts.get(artifact_id)


class DownloadArtifactTest(unittest.IsolatedAsyncioTestCase):
    async def test_missing_artifact_returns_404(self):
        app.state.store = FakeStore({})
        with self.assertRaises(HTTPException) as ctx:
            await download_artifact("artifact_missing")
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_artifact_with_missing_file_returns_404(self):
        app.state.store = FakeStore(
            {
                "artifact_1": {
                    "storage_path": "/nonexistent/path/chart.png",
                    "mime_type": "image/png",
                    "filename": "chart.png",
                }
            }
        )
        with self.assertRaises(HTTPException) as ctx:
            await download_artifact("artifact_1")
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_existing_artifact_returns_file_response(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "chart.png"
            path.write_bytes(b"fake-png-bytes")
            app.state.store = FakeStore(
                {
                    "artifact_2": {
                        "storage_path": str(path),
                        "mime_type": "image/png",
                        "filename": "chart.png",
                    }
                }
            )
            response = await download_artifact("artifact_2")
            self.assertEqual(response.media_type, "image/png")
            self.assertEqual(response.filename, "chart.png")


if __name__ == "__main__":
    unittest.main()
