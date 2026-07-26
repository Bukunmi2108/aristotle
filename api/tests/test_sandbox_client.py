import asyncio
import unittest
from types import SimpleNamespace

import httpx

from app.services.sandbox_client import SandboxClient, SandboxError, Workspace


def _settings():
    return SimpleNamespace(
        sandbox_service_base_url="http://sandbox:7860",
        sandbox_service_token="secret-token",
        sandbox_request_timeout_seconds=30,
        sandbox_command_timeout_seconds=120,
    )


class SandboxClientTest(unittest.TestCase):
    def setUp(self):
        self.requests: list[httpx.Request] = []

    def _client(self, handler) -> SandboxClient:
        def capture(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return handler(request)

        http = httpx.AsyncClient(transport=httpx.MockTransport(capture))
        return SandboxClient(http=http, settings=_settings())

    def test_exec_posts_command_and_sends_token(self):
        def handler(request):
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "stdout": "hi",
                    "stderr": "",
                    "exit_code": 0,
                    "timed_out": False,
                    "duration_ms": 5,
                },
            )

        client = self._client(handler)
        result = asyncio.run(client.exec("conv1", "echo hi"))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["stdout"], "hi")
        request = self.requests[-1]
        self.assertEqual(request.url.path, "/workspaces/conv1/exec")
        self.assertEqual(request.headers["Authorization"], "Bearer secret-token")

    def test_read_file_returns_bytes(self):
        client = self._client(lambda r: httpx.Response(200, content=b"file-bytes"))
        data = asyncio.run(client.read_file("c", "a.txt"))
        self.assertEqual(data, b"file-bytes")
        self.assertEqual(self.requests[-1].url.params["path"], "a.txt")

    def test_write_file_sends_body(self):
        client = self._client(
            lambda r: httpx.Response(200, json={"ok": True, "path": "a.txt", "size": 3})
        )
        result = asyncio.run(client.write_file("c", "a.txt", b"abc"))
        self.assertEqual(result["size"], 3)
        self.assertEqual(self.requests[-1].content, b"abc")

    def test_list_dir_returns_entries(self):
        client = self._client(
            lambda r: httpx.Response(
                200,
                json={
                    "path": ".",
                    "entries": [
                        {
                            "name": "a.txt",
                            "path": "a.txt",
                            "type": "file",
                            "size": 1,
                            "mtime": 0.0,
                        }
                    ],
                },
            )
        )
        entries = asyncio.run(client.list_dir("c"))
        self.assertEqual(entries[0]["name"], "a.txt")

    def test_export_document_uses_fixed_export_endpoint(self):
        client = self._client(
            lambda r: httpx.Response(
                200,
                json={
                    "source_path": "report.md",
                    "output_path": "report.pdf",
                    "mime_type": "application/pdf",
                    "size": 1024,
                },
            )
        )

        result = asyncio.run(
            client.export_document("c", "report.md", "report.pdf", "Report")
        )

        self.assertEqual(result["output_path"], "report.pdf")
        self.assertEqual(self.requests[-1].url.path, "/workspaces/c/export")
        self.assertIn(b'"source_path":"report.md"', self.requests[-1].content)

    def test_error_response_raises_sandbox_error_with_detail(self):
        client = self._client(
            lambda r: httpx.Response(404, json={"detail": "File not found: x"})
        )
        with self.assertRaises(SandboxError) as ctx:
            asyncio.run(client.read_file("c", "x"))
        self.assertIn("File not found", str(ctx.exception))

    def test_exec_stream_forwards_chunks_and_returns_result(self):
        ndjson = (
            '{"type": "stdout", "text": "hello\\n"}\n'
            '{"type": "result", "status": "ok", "stdout": "hello\\n", '
            '"stderr": "", "exit_code": 0, "timed_out": false, "duration_ms": 4}\n'
        )
        client = self._client(lambda r: httpx.Response(200, content=ndjson.encode()))
        seen: list[dict] = []

        async def on_event(event):
            seen.append(event)

        result = asyncio.run(client.exec_stream("c", "echo hello", on_event))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(seen[0]["type"], "stdout")
        self.assertIn("hello", seen[0]["text"])

    def test_exec_stream_raises_on_error_line(self):
        ndjson = '{"type": "error", "message": "bad conversation"}\n'
        client = self._client(lambda r: httpx.Response(200, content=ndjson.encode()))

        async def on_event(event):
            pass

        with self.assertRaises(SandboxError):
            asyncio.run(client.exec_stream("c", "x", on_event))

    def test_destroy_is_best_effort_on_error(self):
        client = self._client(lambda r: httpx.Response(500, json={"detail": "boom"}))
        # Should not raise.
        asyncio.run(client.destroy("c"))

    def test_no_token_omits_authorization_header(self):
        settings = _settings()
        settings.sandbox_service_token = None
        http = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: self.requests.append(r)
                or httpx.Response(200, json={"path": ".", "entries": []})
            )
        )
        client = SandboxClient(http=http, settings=settings)
        asyncio.run(client.list_dir("c"))
        self.assertNotIn("authorization", self.requests[-1].headers)


class WorkspaceHandleTest(unittest.TestCase):
    def test_handle_binds_conversation_id(self):
        seen: list[str] = []

        class FakeClient:
            async def exec(self, cid, command, timeout=None):
                seen.append(cid)
                return {"status": "ok"}

        workspace = Workspace(FakeClient(), "conv-42")
        asyncio.run(workspace.exec("echo hi"))
        self.assertEqual(seen, ["conv-42"])


if __name__ == "__main__":
    unittest.main()
