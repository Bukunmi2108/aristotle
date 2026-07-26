from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

import httpx

from app.config import ApiSettings


logger = logging.getLogger(__name__)


class SandboxError(Exception):
    """A workspace operation failed in the sandbox service."""


class SandboxClient:
    """Thin HTTP client for the private sandbox service.

    Mirrors `SearchClient`/`ModelClient`: the API owns orchestration and only
    reaches the sandbox over the internal network with a bearer token. The
    sandbox is the single owner of workspace files and the only place code runs.
    """

    def __init__(self, *, http: httpx.AsyncClient, settings: ApiSettings):
        self.http = http
        self.base_url = settings.sandbox_service_base_url.rstrip("/")
        self.token = settings.sandbox_service_token
        self.request_timeout = settings.sandbox_request_timeout_seconds
        self.command_timeout = settings.sandbox_command_timeout_seconds

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _url(self, conversation_id: str, suffix: str = "") -> str:
        return f"{self.base_url}/workspaces/{conversation_id}{suffix}"

    async def readyz(self) -> bool:
        try:
            response = await self.http.get(f"{self.base_url}/readyz", timeout=5)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def exec(
        self, conversation_id: str, command: str, timeout_seconds: float | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"command": command}
        if timeout_seconds is not None:
            payload["timeout_seconds"] = timeout_seconds
        # Outlast the sandbox's own command timeout so the HTTP client doesn't
        # trip first on a slow-but-valid build.
        budget = (timeout_seconds or self.command_timeout) + 15
        response = await self.http.post(
            self._url(conversation_id, "/exec"),
            json=payload,
            headers=self._headers(),
            timeout=budget,
        )
        return _json_or_raise(response)

    async def exec_stream(
        self,
        conversation_id: str,
        command: str,
        on_event: Callable[[dict[str, Any]], Awaitable[None]],
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Stream a command: call on_event for each stdout/stderr chunk, then
        return the final result dict. Consumes the sandbox's NDJSON stream.
        """
        payload: dict[str, Any] = {"command": command}
        if timeout_seconds is not None:
            payload["timeout_seconds"] = timeout_seconds
        budget = (timeout_seconds or self.command_timeout) + 15
        result: dict[str, Any] | None = None
        async with self.http.stream(
            "POST",
            self._url(conversation_id, "/exec_stream"),
            json=payload,
            headers=self._headers(),
            timeout=budget,
        ) as response:
            if response.status_code >= 400:
                await response.aread()
                _raise_for_status(response)
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                event = json.loads(line)
                kind = event.get("type")
                if kind == "result":
                    result = event
                elif kind == "error":
                    raise SandboxError(event.get("message", "Command failed."))
                else:
                    await on_event(event)
        if result is None:
            raise SandboxError("Command stream ended without a result.")
        return result

    async def list_dir(
        self, conversation_id: str, path: str = "."
    ) -> list[dict[str, Any]]:
        response = await self.http.get(
            self._url(conversation_id, "/list"),
            params={"path": path},
            headers=self._headers(),
            timeout=self.request_timeout,
        )
        return _json_or_raise(response)["entries"]

    async def read_file(self, conversation_id: str, path: str) -> bytes:
        response = await self.http.get(
            self._url(conversation_id, "/file"),
            params={"path": path},
            headers=self._headers(),
            timeout=self.request_timeout,
        )
        _raise_for_status(response)
        return response.content

    async def write_file(
        self, conversation_id: str, path: str, data: bytes
    ) -> dict[str, Any]:
        response = await self.http.put(
            self._url(conversation_id, "/file"),
            params={"path": path},
            content=data,
            headers=self._headers(),
            timeout=self.request_timeout,
        )
        return _json_or_raise(response)

    async def make_dir(self, conversation_id: str, path: str) -> None:
        response = await self.http.post(
            self._url(conversation_id, "/mkdir"),
            json={"path": path},
            headers=self._headers(),
            timeout=self.request_timeout,
        )
        _json_or_raise(response)

    async def export_document(
        self,
        conversation_id: str,
        source_path: str,
        output_path: str,
        title: str | None = None,
    ) -> dict[str, Any]:
        response = await self.http.post(
            self._url(conversation_id, "/export"),
            json={
                "source_path": source_path,
                "output_path": output_path,
                "title": title,
            },
            headers=self._headers(),
            timeout=self.command_timeout + 15,
        )
        return _json_or_raise(response)

    async def move(self, conversation_id: str, src: str, dst: str) -> None:
        response = await self.http.post(
            self._url(conversation_id, "/move"),
            json={"src": src, "dst": dst},
            headers=self._headers(),
            timeout=self.request_timeout,
        )
        _json_or_raise(response)

    async def delete(self, conversation_id: str, path: str) -> None:
        response = await self.http.request(
            "DELETE",
            self._url(conversation_id, "/file"),
            params={"path": path},
            headers=self._headers(),
            timeout=self.request_timeout,
        )
        _json_or_raise(response)

    async def destroy(self, conversation_id: str) -> None:
        try:
            response = await self.http.request(
                "DELETE",
                self._url(conversation_id),
                headers=self._headers(),
                timeout=self.request_timeout,
            )
            _json_or_raise(response)
        except (httpx.HTTPError, SandboxError) as exc:
            # Best-effort cleanup — don't fail the delete, but log it since
            # repeated failures leak workspace directories.
            logger.warning(
                "Failed to destroy sandbox workspace %s: %s", conversation_id, exc
            )


class Workspace:
    """Per-conversation handle: a `SandboxClient` with the conversation id bound."""

    def __init__(self, client: SandboxClient, conversation_id: str):
        self._client = client
        self.conversation_id = conversation_id

    async def exec(self, command: str, timeout_seconds: float | None = None):
        return await self._client.exec(self.conversation_id, command, timeout_seconds)

    async def exec_stream(self, command, on_event, timeout_seconds=None):
        return await self._client.exec_stream(
            self.conversation_id, command, on_event, timeout_seconds
        )

    async def list_dir(self, path: str = "."):
        return await self._client.list_dir(self.conversation_id, path)

    async def read_file(self, path: str) -> bytes:
        return await self._client.read_file(self.conversation_id, path)

    async def write_file(self, path: str, data: bytes):
        return await self._client.write_file(self.conversation_id, path, data)

    async def make_dir(self, path: str) -> None:
        await self._client.make_dir(self.conversation_id, path)

    async def export_document(
        self, source_path: str, output_path: str, title: str | None = None
    ):
        return await self._client.export_document(
            self.conversation_id, source_path, output_path, title
        )

    async def move(self, src: str, dst: str) -> None:
        await self._client.move(self.conversation_id, src, dst)

    async def delete(self, path: str) -> None:
        await self._client.delete(self.conversation_id, path)


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    detail = None
    try:
        body = response.json()
        detail = body.get("detail") if isinstance(body, dict) else None
    except Exception:
        detail = None
    raise SandboxError(detail or f"Sandbox request failed ({response.status_code}).")


def _json_or_raise(response: httpx.Response) -> Any:
    _raise_for_status(response)
    return response.json()
