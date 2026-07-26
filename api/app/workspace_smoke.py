"""Deployment smoke test for API-to-sandbox DNS, auth, and filesystem I/O."""

from __future__ import annotations

import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen


CONVERSATION_ID = "deployment-smoke"
FILE_PATH = "health/probe.txt"
CONTENT = b"aristotle-workspace-ok"


def _request(
    method: str,
    suffix: str,
    *,
    data: bytes | None = None,
    content_type: str | None = None,
) -> bytes:
    base_url = os.getenv(
        "SANDBOX_SERVICE_BASE_URL", "http://workspace-aristotle-sandbox:7860"
    ).rstrip("/")
    headers: dict[str, str] = {}
    token = os.getenv("SANDBOX_SERVICE_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if content_type:
        headers["Content-Type"] = content_type
    request = Request(
        f"{base_url}{suffix}",
        data=data,
        headers=headers,
        method=method,
    )
    with urlopen(request, timeout=10) as response:
        return response.read()


def main() -> None:
    workspace = f"/workspaces/{CONVERSATION_ID}"
    workspace_created = False
    try:
        _request("GET", "/readyz")
        _request(
            "POST",
            f"{workspace}/mkdir",
            data=json.dumps({"path": "health"}).encode(),
            content_type="application/json",
        )
        workspace_created = True
        query = urlencode({"path": FILE_PATH})
        _request("PUT", f"{workspace}/file?{query}", data=CONTENT)
        actual = _request("GET", f"{workspace}/file?{query}")
        if actual != CONTENT:
            raise RuntimeError("Workspace smoke-test content did not round-trip.")
    finally:
        if workspace_created:
            _request("DELETE", workspace)
    print("Workspace DNS, authentication, and file I/O smoke test passed.")


if __name__ == "__main__":
    main()
