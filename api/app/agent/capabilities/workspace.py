from __future__ import annotations

import logging
import mimetypes
import posixpath
from dataclasses import dataclass
from typing import Literal, NoReturn
from uuid import uuid4

from pydantic import BaseModel
from pydantic_ai import ModelRetry, ToolDefinition
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.toolsets.function import FunctionToolset
from pydantic_ai.tools import RunContext

from app.agent.deps import AgentDeps
from app.services.sandbox_client import SandboxError, Workspace


logger = logging.getLogger(__name__)


WORKSPACE_TOOL_NAMES = {
    "run_command",
    "run_python",
    "list_dir",
    "read_workspace_file",
    "write_file",
    "make_dir",
    "move_path",
    "delete_path",
    "present_file",
    "export_document",
}
MAX_READ_CHARS = 20_000


class CommandResult(BaseModel):
    status: str
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    duration_ms: int


class FileNode(BaseModel):
    name: str
    path: str
    type: str
    size: int


class DirListing(BaseModel):
    path: str
    entries: list[FileNode]


class FileContent(BaseModel):
    path: str
    content: str
    truncated: bool = False


class WriteResult(BaseModel):
    path: str
    size: int


class OkResult(BaseModel):
    ok: bool = True
    detail: str | None = None


class PresentResult(BaseModel):
    path: str
    title: str | None = None
    mime_type: str
    version: int


class ExportDocumentResult(BaseModel):
    source_path: str
    artifacts: list[PresentResult]


@dataclass
class WorkspaceTools(AbstractCapability[AgentDeps]):
    def get_instructions(self):
        def instructions(ctx: RunContext[AgentDeps]) -> str | None:
            if not ctx.deps.workspace_tools_enabled:
                return None
            return (
                "A persistent workspace is available for this conversation: a real "
                "working directory you can build up over multiple turns. Use "
                "write_file/make_dir to create files and folders, run_command to "
                "execute anything (shell, node, build tools) and run_python for "
                "quick Python, and read_workspace_file/list_dir to inspect your own "
                "work. "
                "Files persist across turns in this conversation. Prefer running "
                "code to compute values instead of doing arithmetic yourself, and "
                "always print the result you need. If a command fails or times out, "
                "report what went wrong instead of guessing at the output.\n\n"
                "When you produce a finished, self-contained output worth viewing or "
                "downloading — a report, chart, generated page, document, or dataset "
                "— call present_file to show it in the side panel. Prefer answering "
                "inline; only present substantial finished artifacts, not scratch or "
                "intermediate files, and present one at a time. Presenting the same "
                "path again updates it in place as a new version. For format-only "
                "follow-ups, reuse the existing workspace file without researching "
                "again. Use export_document for Markdown/PDF requests; it converts "
                "and presents every requested format, so do not separately call "
                "present_file for those outputs."
            )

        return instructions

    def get_toolset(self) -> FunctionToolset[AgentDeps]:
        toolset = FunctionToolset[AgentDeps](id="workspace_tools", strict=False)

        @toolset.tool(name="run_command", strict=False)
        async def run_command(
            ctx: RunContext[AgentDeps],
            command: str,
            timeout_seconds: float | None = None,
        ) -> CommandResult:
            """Run a shell command in the conversation workspace."""
            return await _exec(ctx, command, timeout_seconds)

        @toolset.tool(name="run_python", strict=False)
        async def run_python(ctx: RunContext[AgentDeps], code: str) -> CommandResult:
            """Run a Python snippet in the workspace. Print whatever you need to see."""
            workspace = _workspace(ctx)
            script = f".aristotle/run_{uuid4().hex}.py"
            try:
                await workspace.write_file(script, code.encode())
                result = _command_result(await workspace.exec(f"python3 {script}"))
            except SandboxError as exc:
                await _fail(ctx, "run_python", str(exc))
            await _record_run(ctx, kind="python", command=code, result=result)
            return result

        @toolset.tool(name="list_dir", strict=False)
        async def list_dir(ctx: RunContext[AgentDeps], path: str = ".") -> DirListing:
            """List files and folders in the workspace."""
            try:
                entries = await _workspace(ctx).list_dir(path)
            except SandboxError as exc:
                await _fail(ctx, "list_dir", str(exc))
            return DirListing(
                path=path, entries=[FileNode(**_node_fields(node)) for node in entries]
            )

        @toolset.tool(name="read_workspace_file", strict=False)
        async def read_workspace_file(
            ctx: RunContext[AgentDeps], path: str
        ) -> FileContent:
            """Read a text file from the workspace."""
            try:
                data = await _workspace(ctx).read_file(path)
            except SandboxError as exc:
                await _fail(ctx, "read_workspace_file", str(exc))
            text = data.decode(errors="replace")
            truncated = len(text) > MAX_READ_CHARS
            return FileContent(
                path=path, content=text[:MAX_READ_CHARS], truncated=truncated
            )

        @toolset.tool(name="write_file", strict=False)
        async def write_file(
            ctx: RunContext[AgentDeps], path: str, content: str
        ) -> WriteResult:
            """Write a text file into the workspace, creating parent folders."""
            try:
                result = await _workspace(ctx).write_file(path, content.encode())
            except SandboxError as exc:
                await _fail(ctx, "write_file", str(exc))
            return WriteResult(path=path, size=result["size"])

        @toolset.tool(name="make_dir", strict=False)
        async def make_dir(ctx: RunContext[AgentDeps], path: str) -> OkResult:
            """Create a directory (and parents) in the workspace."""
            try:
                await _workspace(ctx).make_dir(path)
            except SandboxError as exc:
                await _fail(ctx, "make_dir", str(exc))
            return OkResult()

        @toolset.tool(name="move_path", strict=False)
        async def move_path(ctx: RunContext[AgentDeps], src: str, dst: str) -> OkResult:
            """Move or rename a file/folder in the workspace."""
            try:
                await _workspace(ctx).move(src, dst)
            except SandboxError as exc:
                await _fail(ctx, "move_path", str(exc))
            return OkResult()

        @toolset.tool(name="delete_path", strict=False)
        async def delete_path(ctx: RunContext[AgentDeps], path: str) -> OkResult:
            """Delete a file or folder from the workspace."""
            try:
                await _workspace(ctx).delete(path)
            except SandboxError as exc:
                await _fail(ctx, "delete_path", str(exc))
            return OkResult()

        @toolset.tool(name="present_file", strict=False)
        async def present_file(
            ctx: RunContext[AgentDeps], path: str, title: str | None = None
        ) -> PresentResult:
            """Show a finished workspace file to the user in the side panel."""
            return await _present(ctx, path, title, tool="present_file")

        @toolset.tool(name="export_document", strict=False)
        async def export_document(
            ctx: RunContext[AgentDeps],
            source_path: str,
            formats: list[Literal["markdown", "pdf"]],
            title: str | None = None,
        ) -> ExportDocumentResult:
            """Reuse a Markdown file, export requested formats, and present every output."""
            requested = list(dict.fromkeys(formats))
            if not requested:
                await _fail(ctx, "export_document", "At least one format is required.")
            workspace = _workspace(ctx)
            if not await _exists(workspace, source_path):
                await _fail(
                    ctx,
                    "export_document",
                    f"Cannot export '{source_path}': not found in workspace.",
                )
            suffix = posixpath.splitext(source_path)[1].lower()
            if suffix not in {".md", ".markdown"}:
                await _fail(
                    ctx,
                    "export_document",
                    "PDF export currently supports Markdown source files only.",
                )

            output_paths: list[str] = []
            if "markdown" in requested:
                output_paths.append(source_path)
            if "pdf" in requested:
                pdf_path = posixpath.splitext(source_path)[0] + ".pdf"
                try:
                    await workspace.export_document(source_path, pdf_path, title)
                except SandboxError as exc:
                    await _fail(ctx, "export_document", str(exc))
                output_paths.append(pdf_path)

            artifacts = [
                await _present(ctx, path, title, tool="export_document")
                for path in output_paths
            ]
            return ExportDocumentResult(
                source_path=source_path,
                artifacts=artifacts,
            )

        return toolset

    async def prepare_tools(
        self,
        ctx: RunContext[AgentDeps],
        tool_defs: list[ToolDefinition],
    ) -> list[ToolDefinition]:
        if ctx.deps.workspace_tools_enabled:
            return tool_defs
        return [tool for tool in tool_defs if tool.name not in WORKSPACE_TOOL_NAMES]


async def _present(
    ctx: RunContext[AgentDeps],
    path: str,
    title: str | None,
    *,
    tool: str,
) -> PresentResult:
    workspace = _workspace(ctx)
    if not await _exists(workspace, path):
        await _fail(ctx, tool, f"Cannot present '{path}': not found in workspace.")
    mime_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    artifact_id = f"pres_{uuid4().hex}"
    version = 1
    store = ctx.deps.document_store
    try:
        data = await workspace.read_file(path)
        snapshot_path = _snapshot_path(artifact_id, path)
        await workspace.write_file(snapshot_path, data)
    except SandboxError as exc:
        await _fail(ctx, tool, str(exc))
    if store is not None:
        record = await store.create_presentation(
            presentation_id=artifact_id,
            conversation_id=workspace.conversation_id,
            message_id=ctx.deps.events.message_id,
            path=path,
            snapshot_path=snapshot_path,
            mime_type=mime_type,
            title=title,
            size_bytes=len(data),
        )
        artifact_id = record["id"]
        version = record["version"]
    await ctx.deps.events.send(
        "workspace.present",
        artifact_id=artifact_id,
        path=path,
        mime_type=mime_type,
        title=title,
        version=version,
        size_bytes=len(data),
    )
    return PresentResult(path=path, title=title, mime_type=mime_type, version=version)


def _workspace(ctx: RunContext[AgentDeps]) -> Workspace:
    workspace = ctx.deps.workspace
    if workspace is None:
        raise ValueError("Workspace is not configured for this run.")
    return workspace


async def _fail(ctx: RunContext[AgentDeps], tool: str, message: str) -> NoReturn:
    """Raise a recoverable tool failure for the runtime to publish once."""
    raise ModelRetry(message)


async def _exists(workspace: Workspace, path: str) -> bool:
    cleaned = path.strip("/")
    parent = posixpath.dirname(cleaned) or "."
    name = posixpath.basename(cleaned)
    try:
        entries = await workspace.list_dir(parent)
    except SandboxError:
        return False
    return any(entry["name"] == name for entry in entries)


async def _exec(
    ctx: RunContext[AgentDeps], command: str, timeout_seconds: float | None
) -> CommandResult:
    async def on_event(event: dict) -> None:
        await ctx.deps.events.send(
            "terminal.output",
            tool="run_command",
            tool_call_id=ctx.tool_call_id,
            stream=event.get("type"),
            text=event.get("text", ""),
        )

    try:
        payload = await _workspace(ctx).exec_stream(command, on_event, timeout_seconds)
    except SandboxError as exc:
        await _fail(ctx, "run_command", str(exc))
    result = _command_result(payload)
    await _record_run(ctx, kind="command", command=command, result=result)
    return result


async def _record_run(
    ctx: RunContext[AgentDeps], *, kind: str, command: str, result: CommandResult
) -> None:
    # Best-effort audit: a DB hiccup must never fail an otherwise-successful run.
    store = ctx.deps.document_store
    workspace = ctx.deps.workspace
    if store is None or workspace is None:
        return
    try:
        await store.record_workspace_run(
            workspace_run_id=f"wsr_{uuid4().hex}",
            conversation_id=workspace.conversation_id,
            command=command,
            kind=kind,
            status=result.status,
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
        )
    except Exception:
        logger.warning(
            "workspace run audit failed for %s",
            workspace.conversation_id,
            exc_info=True,
        )


def _command_result(payload: dict) -> CommandResult:
    return CommandResult(
        status=payload["status"],
        stdout=payload["stdout"],
        stderr=payload["stderr"],
        exit_code=payload["exit_code"],
        timed_out=payload["timed_out"],
        duration_ms=payload["duration_ms"],
    )


def _node_fields(node: dict) -> dict:
    return {
        "name": node["name"],
        "path": node["path"],
        "type": node["type"],
        "size": node["size"],
    }


def _snapshot_path(presentation_id: str, path: str) -> str:
    """Return a presentation-owned path so later source edits cannot rewrite history."""
    filename = posixpath.basename(path.strip("/")) or "artifact"
    return f".aristotle/presentations/{presentation_id}/{filename}"
