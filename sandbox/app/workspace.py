import asyncio
import os
import re
import resource
import signal
from pathlib import Path
from shutil import rmtree
from time import monotonic

from app.config import SandboxSettings
from app.models import ExecResult, FileNode

# Leading alphanumeric required so an id can never be a traversal token
# (".", "..") that _conversation_dir/destroy would resolve to the root.
CONVERSATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

DEFAULT_PATH = "/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin"


class WorkspaceError(Exception):
    """Base class for workspace failures, mapped to HTTP status in main.py."""


class InvalidConversationError(WorkspaceError):
    pass


class PathEscapeError(WorkspaceError):
    pass


class NotFoundError(WorkspaceError):
    pass


class WorkspaceManager:
    """Owns per-conversation directories under one root and runs commands in them.

    One long-lived manager serves every conversation; each conversation gets its
    own subdirectory. Isolation between conversations is soft (subdirs), which is
    acceptable for a personal single-user tool — the hard boundary is the
    container this whole service runs in.
    """

    def __init__(self, settings: SandboxSettings):
        self.settings = settings
        self.root = Path(settings.workspace_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _conversation_dir(self, conversation_id: str) -> Path:
        if not CONVERSATION_ID_RE.match(conversation_id):
            raise InvalidConversationError(
                f"Invalid conversation id: {conversation_id!r}"
            )
        return self.root / conversation_id

    def ensure(self, conversation_id: str) -> Path:
        directory = self._conversation_dir(conversation_id)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def resolve(self, conversation_id: str, rel_path: str) -> Path:
        """Resolve rel_path inside the conversation workspace, or raise.

        `.resolve()` first collapses any symlinks and `..`, so the subsequent
        lexical containment check is correct even against symlink escapes. An
        absolute rel_path is interpreted relative to the workspace root, never
        the host root.
        """
        base = self.ensure(conversation_id)
        cleaned = rel_path.lstrip("/") or "."
        candidate = (base / cleaned).resolve()
        if candidate != base and not candidate.is_relative_to(base):
            raise PathEscapeError(f"Path escapes the workspace: {rel_path!r}")
        return candidate

    def read_file(self, conversation_id: str, rel_path: str) -> bytes:
        path = self.resolve(conversation_id, rel_path)
        if not path.is_file():
            raise NotFoundError(f"File not found: {rel_path!r}")
        return path.read_bytes()

    def write_file(self, conversation_id: str, rel_path: str, data: bytes) -> int:
        path = self.resolve(conversation_id, rel_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return len(data)

    def list_dir(self, conversation_id: str, rel_path: str) -> list[FileNode]:
        path = self.resolve(conversation_id, rel_path)
        if not path.exists():
            raise NotFoundError(f"Directory not found: {rel_path!r}")
        if not path.is_dir():
            raise WorkspaceError(f"Not a directory: {rel_path!r}")
        base = self.ensure(conversation_id)
        entries: list[FileNode] = []
        for child in sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name)):
            stat = child.stat()
            entries.append(
                FileNode(
                    name=child.name,
                    path=str(child.relative_to(base)),
                    type="dir" if child.is_dir() else "file",
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                )
            )
        return entries

    def make_dir(self, conversation_id: str, rel_path: str) -> None:
        path = self.resolve(conversation_id, rel_path)
        path.mkdir(parents=True, exist_ok=True)

    def move(self, conversation_id: str, src: str, dst: str) -> None:
        source = self.resolve(conversation_id, src)
        target = self.resolve(conversation_id, dst)
        if not source.exists():
            raise NotFoundError(f"Path not found: {src!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        source.replace(target)

    def delete(self, conversation_id: str, rel_path: str) -> None:
        path = self.resolve(conversation_id, rel_path)
        if not path.exists():
            raise NotFoundError(f"Path not found: {rel_path!r}")
        if path.is_dir():
            rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)

    def destroy(self, conversation_id: str) -> None:
        directory = self._conversation_dir(conversation_id)
        rmtree(directory, ignore_errors=True)

    async def exec(
        self,
        conversation_id: str,
        command: str,
        timeout_seconds: float | None = None,
    ) -> ExecResult:
        """Buffered execution: drain the stream and return the final result."""
        result: dict | None = None
        async for event in self.exec_stream(conversation_id, command, timeout_seconds):
            if event["type"] == "result":
                result = event
        if result is None:
            raise WorkspaceError("Command produced no result event.")
        return ExecResult(**{k: v for k, v in result.items() if k != "type"})

    async def exec_stream(
        self,
        conversation_id: str,
        command: str,
        timeout_seconds: float | None = None,
    ):
        """Run a command, yielding {"type": "stdout"|"stderr", "text"} chunks as
        they arrive, then a final {"type": "result", ...} with the buffered
        (truncated) output, exit code, and status.
        """
        workdir = self.ensure(conversation_id)
        timeout = timeout_seconds or self.settings.command_timeout_seconds
        max_chars = self.settings.max_output_chars

        started = monotonic()
        process = await asyncio.create_subprocess_exec(
            "/bin/sh",
            "-c",
            command,
            cwd=str(workdir),
            env={
                "PATH": os.environ.get("PATH", DEFAULT_PATH),
                "HOME": str(workdir),
                "LANG": os.environ.get("LANG", "C.UTF-8"),
            },
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            preexec_fn=self._build_preexec(),
        )

        queue: asyncio.Queue = asyncio.Queue()

        async def pump(stream, name: str) -> None:
            try:
                while True:
                    chunk = await stream.read(4096)
                    if not chunk:
                        break
                    await queue.put((name, chunk.decode(errors="replace")))
            finally:
                await queue.put((name, None))

        pumps = [
            asyncio.create_task(pump(process.stdout, "stdout")),
            asyncio.create_task(pump(process.stderr, "stderr")),
        ]

        buffers = {"stdout": [], "stderr": []}
        lengths = {"stdout": 0, "stderr": 0}
        finished = 0
        timed_out = False
        try:
            while finished < 2:
                remaining = timeout - (monotonic() - started)
                if remaining <= 0:
                    raise TimeoutError
                name, text = await asyncio.wait_for(queue.get(), timeout=remaining)
                if text is None:
                    finished += 1
                    continue
                if lengths[name] < max_chars:
                    piece = text[: max_chars - lengths[name]]
                    buffers[name].append(piece)
                    lengths[name] += len(piece)
                yield {"type": name, "text": text}
        except TimeoutError:
            timed_out = True
            self._kill_process_group(process)

        # A process that closes both pipes but keeps running exits the drain loop
        # normally, so the timeout must also cover the final wait.
        if not timed_out:
            remaining = timeout - (monotonic() - started)
            if remaining <= 0:
                timed_out = True
                self._kill_process_group(process)
            else:
                try:
                    await asyncio.wait_for(process.wait(), timeout=remaining)
                except TimeoutError:
                    timed_out = True
                    self._kill_process_group(process)

        for task in pumps:
            task.cancel()
        # Await the cancelled pumps so their CancelledError isn't left dangling.
        await asyncio.gather(*pumps, return_exceptions=True)
        await process.wait()

        duration_ms = int((monotonic() - started) * 1000)
        stdout = "".join(buffers["stdout"])
        stderr = "".join(buffers["stderr"])
        if timed_out:
            stderr = (stderr + "\n\nCommand timed out.").strip()

        exit_code = process.returncode if process.returncode is not None else -1
        if timed_out:
            status = "timeout"
        elif exit_code == 0:
            status = "ok"
        else:
            status = "error"

        yield {
            "type": "result",
            "status": status,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
            "timed_out": timed_out,
            "duration_ms": duration_ms,
        }

    def _build_preexec(self):
        cpu = self.settings.cpu_seconds
        memory = self.settings.memory_bytes
        fsize = self.settings.fsize_bytes
        nofile = self.settings.nofile_limit

        def preexec() -> None:
            # New session/process group so a timeout can kill the whole tree.
            os.setsid()
            if cpu > 0:
                resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
            if memory > 0:
                resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
            if fsize > 0:
                resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
            if nofile > 0:
                resource.setrlimit(resource.RLIMIT_NOFILE, (nofile, nofile))

        return preexec

    @staticmethod
    def _kill_process_group(process: asyncio.subprocess.Process) -> None:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                process.kill()
            except ProcessLookupError:
                pass
