import asyncio
import errno
import mimetypes
import os
import resource
import signal
import time
from pathlib import Path
from shutil import rmtree
from time import monotonic
from uuid import uuid4

import pyseccomp as seccomp

from app.config import ApiSettings
from app.db import PersistenceStore
from app.models import ArtifactRecord, SandboxRunResult, SandboxRunStatus
from app.services.sandbox_ast import validate_python_source


SESSION_MAX_AGE_MULTIPLIER = 10
BLOCKED_NETWORK_SYSCALLS = (
    "socket", "connect", "bind", "sendto", "recvfrom", "accept", "accept4",
)
BLOCKED_ESCALATION_SYSCALLS = (
    "mount", "umount2", "unshare", "setns", "ptrace", "keyctl", "chroot",
)
DB_STATUS_BY_RESULT_STATUS = {
    "ok": "complete",
    "error": "error",
    "timeout": "timeout",
    "rejected": "error",
}


class SandboxSession:
    """One persistent workspace for the lifetime of a single chat run.

    Scoped per-run (not per-call) so a `run_python` call that loads a CSV and
    a later `generate_chart` call in the same turn can share workspace state —
    the local analog of the container reuse OpenAI/Anthropic's own code
    execution tools rely on. `chat_run_id` identifies that turn; each `run()`
    call separately mints its own `sandbox_run_id` for its own audit-log row —
    these are two different ID spaces, not the same ID under two names.
    """

    def __init__(
        self,
        *,
        chat_run_id: str,
        conversation_id: str,
        workspace_dir: Path,
        settings: ApiSettings,
        document_store: PersistenceStore | None,
    ):
        self.chat_run_id = chat_run_id
        self.conversation_id = conversation_id
        self.workspace_dir = workspace_dir
        self.settings = settings
        self.document_store = document_store
        self.created_at = monotonic()
        self._materialized_file_ids: set[str] = set()

    async def run(
        self, code: str, input_file_ids: list[str] | None = None
    ) -> SandboxRunResult:
        sandbox_run_id = f"sbx_{uuid4().hex}"
        allowed_imports = set(self.settings.sandbox_allowed_imports.split(","))
        try:
            validate_python_source(code, allowed_imports)
        except ValueError as exc:
            return SandboxRunResult(
                status="rejected",
                stdout="",
                stderr=str(exc),
                exit_code=-1,
                timed_out=False,
                duration_ms=0,
                artifacts=[],
            )

        await self._try_create_sandbox_run(sandbox_run_id, code)

        warnings = await self._materialize_files(input_file_ids or [])
        before = self._snapshot_files()
        script_path = self.workspace_dir / f"_script_{uuid4().hex}.py"
        script_path.write_text(code)

        cpu_seconds = self.settings.sandbox_cpu_seconds
        memory_bytes = self.settings.sandbox_memory_bytes
        fsize_bytes = self.settings.sandbox_fsize_bytes
        nofile_limit = self.settings.sandbox_nofile_limit

        def preexec() -> None:
            os.setsid()
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
            resource.setrlimit(resource.RLIMIT_FSIZE, (fsize_bytes, fsize_bytes))
            resource.setrlimit(resource.RLIMIT_NOFILE, (nofile_limit, nofile_limit))
            _apply_seccomp_filter()

        started = monotonic()
        try:
            process = await asyncio.create_subprocess_exec(
                "python3", "-I", str(script_path),
                cwd=str(self.workspace_dir),
                env={
                    "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                    "HOME": str(self.workspace_dir),
                },
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                preexec_fn=preexec,
            )
        except Exception as exc:
            script_path.unlink(missing_ok=True)
            result = SandboxRunResult(
                status="error",
                stdout="",
                stderr=f"Sandbox failed to start: {exc}",
                exit_code=-1,
                timed_out=False,
                duration_ms=int((monotonic() - started) * 1000),
                artifacts=[],
            )
            await self._try_complete_sandbox_run(sandbox_run_id, result)
            return result

        timed_out = False
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=self.settings.sandbox_run_timeout_seconds
            )
        except asyncio.TimeoutError:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout_bytes, stderr_bytes = await process.communicate()

        duration_ms = int((monotonic() - started) * 1000)
        script_path.unlink(missing_ok=True)

        max_chars = self.settings.sandbox_max_output_chars
        stdout = stdout_bytes.decode(errors="replace")[:max_chars]
        stderr = stderr_bytes.decode(errors="replace")[:max_chars]
        if warnings:
            stderr = ("\n".join(warnings) + "\n" + stderr).strip()
        if timed_out:
            stderr = (stderr + "\n\nExecution timed out.").strip()

        exit_code = process.returncode if process.returncode is not None else -1
        status: SandboxRunStatus = (
            "timeout" if timed_out else ("ok" if exit_code == 0 else "error")
        )
        artifacts = await self._collect_artifacts(before, sandbox_run_id)

        result = SandboxRunResult(
            status=status,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            timed_out=timed_out,
            duration_ms=duration_ms,
            artifacts=artifacts,
        )
        await self._try_complete_sandbox_run(sandbox_run_id, result)
        return result

    async def _try_create_sandbox_run(self, sandbox_run_id: str, code: str) -> None:
        if self.document_store is None:
            return
        try:
            await self.document_store.create_sandbox_run(
                sandbox_run_id=sandbox_run_id,
                run_id=self.chat_run_id,
                conversation_id=self.conversation_id,
                code=code,
            )
        except Exception:
            # Audit logging is best-effort: a DB hiccup must not discard an
            # otherwise-successful (or otherwise-informative) execution.
            pass

    async def _try_complete_sandbox_run(
        self, sandbox_run_id: str, result: SandboxRunResult
    ) -> None:
        if self.document_store is None:
            return
        try:
            await self.document_store.complete_sandbox_run(
                sandbox_run_id,
                status=DB_STATUS_BY_RESULT_STATUS[result.status],
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.exit_code,
                duration_ms=result.duration_ms,
            )
        except Exception:
            pass

    async def _materialize_files(self, file_ids: list[str]) -> list[str]:
        warnings: list[str] = []
        if self.document_store is None:
            if file_ids:
                warnings.append(
                    "Input files could not be loaded: document persistence is "
                    "not configured."
                )
            return warnings

        for file_id in file_ids:
            if file_id in self._materialized_file_ids:
                continue
            record = await self.document_store.get_file(file_id)
            if record is None:
                warnings.append(f"Input file '{file_id}' could not be loaded: not found.")
                continue
            source_path = Path(record["storage_path"])
            if not source_path.exists():
                warnings.append(
                    f"Input file '{file_id}' could not be loaded: missing from storage."
                )
                continue
            # Basename only: record["filename"] is the original uploaded name,
            # attacker-controlled and only extension-validated at upload time —
            # taking it as-is here would let a crafted "../../x" escape the
            # workspace directory.
            safe_name = Path(record["filename"]).name
            if not safe_name:
                warnings.append(f"Input file '{file_id}' has an invalid filename.")
                continue
            dest_path = self.workspace_dir / safe_name
            dest_path.write_bytes(source_path.read_bytes())
            self._materialized_file_ids.add(file_id)
        return warnings

    def _snapshot_files(self) -> dict[str, float]:
        return {
            path.name: path.stat().st_mtime
            for path in self.workspace_dir.iterdir()
            if path.is_file()
        }

    async def _collect_artifacts(
        self, before: dict[str, float], sandbox_run_id: str
    ) -> list[ArtifactRecord]:
        artifacts: list[ArtifactRecord] = []
        artifact_base_dir = Path(self.settings.sandbox_artifact_dir).resolve()
        for path in self.workspace_dir.iterdir():
            if not path.is_file() or path.name.startswith("_script_"):
                continue
            mtime = path.stat().st_mtime
            if before.get(path.name) == mtime:
                continue

            mime_type, _ = mimetypes.guess_type(path.name)
            resolved_mime_type = mime_type or "application/octet-stream"
            artifact_id = f"artifact_{uuid4().hex}"

            # Copied out to a persistent location, not left in the session
            # workspace — that workspace gets rmtree'd as soon as this chat
            # turn ends, which would otherwise delete every artifact before
            # a user could ever click its download link.
            artifact_dir = artifact_base_dir / artifact_id
            artifact_dir.mkdir(parents=True, exist_ok=True)
            artifact_path = artifact_dir / path.name
            artifact_path.write_bytes(path.read_bytes())
            size_bytes = artifact_path.stat().st_size

            if self.document_store is not None:
                try:
                    await self.document_store.create_artifact(
                        artifact_id=artifact_id,
                        sandbox_run_id=sandbox_run_id,
                        filename=path.name,
                        mime_type=resolved_mime_type,
                        size_bytes=size_bytes,
                        storage_path=str(artifact_path),
                    )
                except Exception:
                    pass

            artifacts.append(
                ArtifactRecord(
                    id=artifact_id,
                    sandbox_run_id=sandbox_run_id,
                    filename=path.name,
                    mime_type=resolved_mime_type,
                    size_bytes=size_bytes,
                )
            )
        return artifacts


class SandboxExecutor:
    def __init__(
        self, *, settings: ApiSettings, document_store: PersistenceStore | None = None
    ):
        self.settings = settings
        self.document_store = document_store
        self._sessions: dict[str, SandboxSession] = {}
        self._sweep_orphaned_workspaces()

    def get_session(self, run_id: str, conversation_id: str) -> SandboxSession:
        self._evict_stale_sessions()
        session = self._sessions.get(run_id)
        if session is not None:
            return session

        workspace_dir = (Path(self.settings.sandbox_workspace_dir) / run_id).resolve()
        workspace_dir.mkdir(parents=True, exist_ok=True)
        session = SandboxSession(
            chat_run_id=run_id,
            conversation_id=conversation_id,
            workspace_dir=workspace_dir,
            settings=self.settings,
            document_store=self.document_store,
        )
        self._sessions[run_id] = session
        return session

    async def close_session(self, run_id: str) -> None:
        session = self._sessions.pop(run_id, None)
        if session is None:
            return
        rmtree(session.workspace_dir, ignore_errors=True)

    def _evict_stale_sessions(self) -> None:
        max_age = self.settings.sandbox_run_timeout_seconds * SESSION_MAX_AGE_MULTIPLIER
        now = monotonic()
        stale_run_ids = [
            run_id
            for run_id, session in self._sessions.items()
            if now - session.created_at > max_age
        ]
        for run_id in stale_run_ids:
            session = self._sessions.pop(run_id)
            rmtree(session.workspace_dir, ignore_errors=True)

    def _sweep_orphaned_workspaces(self) -> None:
        # Crash-recovery backstop: `_evict_stale_sessions` only ever runs
        # against the in-memory session dict, so a workspace whose session
        # never got a chance to close (process crash/redeploy mid-run) would
        # otherwise sit on disk forever. Uses wall-clock mtime, not
        # `monotonic()` (which resets across restarts and can't be compared
        # to a file's mtime at all).
        base_dir = Path(self.settings.sandbox_workspace_dir).resolve()
        if not base_dir.exists():
            return
        max_age = self.settings.sandbox_run_timeout_seconds * SESSION_MAX_AGE_MULTIPLIER
        cutoff = time.time() - max_age
        for entry in base_dir.iterdir():
            if entry.is_dir() and entry.stat().st_mtime < cutoff:
                rmtree(entry, ignore_errors=True)


def _apply_seccomp_filter() -> None:
    sandbox_filter = seccomp.SyscallFilter(defaction=seccomp.ALLOW)
    for name in BLOCKED_NETWORK_SYSCALLS + BLOCKED_ESCALATION_SYSCALLS:
        sandbox_filter.add_rule(seccomp.ERRNO(errno.EPERM), name)
    sandbox_filter.load()
