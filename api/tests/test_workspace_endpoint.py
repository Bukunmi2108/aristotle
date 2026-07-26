import unittest

from fastapi import HTTPException

from app.main import app, presentation_file, workspace_file
from app.services.sandbox_client import SandboxError


class FakeStore:
    def __init__(self, presentation):
        self._presentation = presentation
        self.calls: list[tuple[str, str]] = []

    async def latest_presentation(self, conversation_id, path):
        self.calls.append((conversation_id, path))
        return self._presentation

    async def get_presentation(self, presentation_id):
        self.calls.append(("presentation", presentation_id))
        return self._presentation


class FakeSandbox:
    def __init__(self, *, data=b"", error=None):
        self._data = data
        self._error = error

    async def read_file(self, conversation_id, path):
        if self._error is not None:
            raise self._error
        return self._data


def _presentation(mime="text/plain"):
    return {
        "id": "pres_1",
        "conversation_id": "conv1",
        "path": "report.txt",
        "snapshot_path": ".aristotle/presentations/pres_1/report.txt",
        "mime_type": mime,
        "version": 1,
    }


class WorkspaceFileEndpointTest(unittest.IsolatedAsyncioTestCase):
    def _configure(self, store, sandbox):
        app.state.store = store
        app.state.sandbox_client = sandbox

    async def test_non_presented_path_is_404_and_never_reads_file(self):
        store = FakeStore(None)
        # A sandbox that would explode if read — proving it is never called.
        sandbox = FakeSandbox(error=AssertionError("must not read a non-presented file"))
        self._configure(store, sandbox)
        with self.assertRaises(HTTPException) as ctx:
            await workspace_file("conv1", "secret.txt")
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(store.calls, [("conv1", "secret.txt")])

    async def test_presented_file_served_inline_with_hardening_headers(self):
        self._configure(FakeStore(_presentation("text/html")), FakeSandbox(data=b"<h1>hi</h1>"))
        response = await workspace_file("conv1", "report.txt")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.body, b"<h1>hi</h1>")
        self.assertEqual(response.media_type, "text/html")
        self.assertIn("inline", response.headers["content-disposition"])
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")

    async def test_download_flag_sets_attachment(self):
        self._configure(FakeStore(_presentation()), FakeSandbox(data=b"x"))
        response = await workspace_file("conv1", "report.txt", download=1)
        self.assertIn("attachment", response.headers["content-disposition"])

    async def test_sandbox_not_found_is_404(self):
        self._configure(
            FakeStore(_presentation()), FakeSandbox(error=SandboxError("File not found"))
        )
        with self.assertRaises(HTTPException) as ctx:
            await workspace_file("conv1", "report.txt")
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_sandbox_unreachable_is_502_not_404(self):
        self._configure(
            FakeStore(_presentation()), FakeSandbox(error=RuntimeError("connection refused"))
        )
        with self.assertRaises(HTTPException) as ctx:
            await workspace_file("conv1", "report.txt")
        self.assertEqual(ctx.exception.status_code, 502)

    async def test_presentation_endpoint_reads_immutable_snapshot(self):
        sandbox = FakeSandbox(data=b"snapshot")
        store = FakeStore(_presentation("text/html"))
        self._configure(store, sandbox)
        response = await presentation_file("pres_1")
        self.assertEqual(response.body, b"snapshot")
        self.assertEqual(store.calls, [("presentation", "pres_1")])

    async def test_presentation_endpoint_rejects_missing_record_without_sandbox_read(self):
        sandbox = FakeSandbox(
            error=AssertionError("must not read an unknown presentation")
        )
        self._configure(FakeStore(None), sandbox)
        with self.assertRaises(HTTPException) as ctx:
            await presentation_file("missing")
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
