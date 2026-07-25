import os
import tempfile
import unittest
from uuid import uuid4

# Configure the service before importing the app (SETTINGS is read at import).
os.environ["SANDBOX_AUTH_TOKEN"] = "test-token"
os.environ["SANDBOX_WORKSPACE_ROOT"] = tempfile.mkdtemp(prefix="sandbox-endpoints-")

from fastapi.testclient import TestClient

from app.main import app

AUTH = {"Authorization": "Bearer test-token"}


class EndpointTest(unittest.TestCase):
    def setUp(self):
        self.ctx = TestClient(app)
        self.client = self.ctx.__enter__()
        self.cid = f"conv-{uuid4().hex}"

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    # ------------------------------------------------------------- health/auth

    def test_healthz_needs_no_auth(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

    def test_readyz_ok(self):
        self.assertEqual(self.client.get("/readyz").status_code, 200)

    def test_exec_without_token_is_rejected(self):
        response = self.client.post(
            f"/workspaces/{self.cid}/exec", json={"command": "echo hi"}
        )
        self.assertEqual(response.status_code, 401)

    def test_exec_with_wrong_token_is_rejected(self):
        response = self.client.post(
            f"/workspaces/{self.cid}/exec",
            json={"command": "echo hi"},
            headers={"Authorization": "Bearer nope"},
        )
        self.assertEqual(response.status_code, 401)

    # ------------------------------------------------------------------- exec

    def test_exec_returns_stdout(self):
        response = self.client.post(
            f"/workspaces/{self.cid}/exec",
            json={"command": "echo hello-endpoint"},
            headers=AUTH,
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertIn("hello-endpoint", body["stdout"])

    def test_exec_timeout(self):
        response = self.client.post(
            f"/workspaces/{self.cid}/exec",
            json={"command": "sleep 5", "timeout_seconds": 1},
            headers=AUTH,
        )
        self.assertEqual(response.json()["status"], "timeout")

    def test_exec_stream_returns_ndjson_events(self):
        response = self.client.post(
            f"/workspaces/{self.cid}/exec_stream",
            json={"command": "echo streamed-endpoint"},
            headers=AUTH,
        )
        self.assertEqual(response.status_code, 200)
        events = [
            __import__("json").loads(line)
            for line in response.text.splitlines()
            if line.strip()
        ]
        self.assertEqual(events[-1]["type"], "result")
        self.assertTrue(
            any(
                e["type"] == "stdout" and "streamed-endpoint" in e["text"]
                for e in events
            )
        )

    def test_exec_stream_requires_token(self):
        response = self.client.post(
            f"/workspaces/{self.cid}/exec_stream", json={"command": "echo hi"}
        )
        self.assertEqual(response.status_code, 401)

    # ------------------------------------------------------------------- files

    def test_write_read_list_roundtrip(self):
        write = self.client.put(
            f"/workspaces/{self.cid}/file",
            params={"path": "docs/report.txt"},
            content=b"report body",
            headers=AUTH,
        )
        self.assertEqual(write.status_code, 200)
        self.assertEqual(write.json()["size"], len(b"report body"))

        read = self.client.get(
            f"/workspaces/{self.cid}/file",
            params={"path": "docs/report.txt"},
            headers=AUTH,
        )
        self.assertEqual(read.status_code, 200)
        self.assertEqual(read.content, b"report body")

        listing = self.client.get(
            f"/workspaces/{self.cid}/list", params={"path": "docs"}, headers=AUTH
        )
        names = [node["name"] for node in listing.json()["entries"]]
        self.assertIn("report.txt", names)

    def test_mkdir_and_delete(self):
        self.client.post(
            f"/workspaces/{self.cid}/mkdir", json={"path": "build"}, headers=AUTH
        )
        listing = self.client.get(
            f"/workspaces/{self.cid}/list", params={"path": "."}, headers=AUTH
        )
        self.assertIn("build", [n["name"] for n in listing.json()["entries"]])

        deleted = self.client.delete(
            f"/workspaces/{self.cid}/file", params={"path": "build"}, headers=AUTH
        )
        self.assertEqual(deleted.status_code, 200)

    def test_exec_output_visible_through_files(self):
        self.client.post(
            f"/workspaces/{self.cid}/exec",
            json={"command": "echo generated > result.txt"},
            headers=AUTH,
        )
        read = self.client.get(
            f"/workspaces/{self.cid}/file", params={"path": "result.txt"}, headers=AUTH
        )
        self.assertEqual(read.content.strip(), b"generated")

    # ------------------------------------------------------------- validation

    def test_path_traversal_rejected(self):
        response = self.client.get(
            f"/workspaces/{self.cid}/file",
            params={"path": "../../etc/passwd"},
            headers=AUTH,
        )
        self.assertEqual(response.status_code, 400)

    def test_read_missing_file_is_404(self):
        response = self.client.get(
            f"/workspaces/{self.cid}/file", params={"path": "missing.txt"}, headers=AUTH
        )
        self.assertEqual(response.status_code, 404)

    def test_destroy_removes_workspace(self):
        self.client.put(
            f"/workspaces/{self.cid}/file",
            params={"path": "a.txt"},
            content=b"x",
            headers=AUTH,
        )
        destroyed = self.client.delete(f"/workspaces/{self.cid}", headers=AUTH)
        self.assertEqual(destroyed.status_code, 200)
        read = self.client.get(
            f"/workspaces/{self.cid}/file", params={"path": "a.txt"}, headers=AUTH
        )
        self.assertEqual(read.status_code, 404)


if __name__ == "__main__":
    unittest.main()
