import os
from dataclasses import dataclass

SERVICE_NAME = "aristotle-sandbox"


@dataclass(frozen=True)
class SandboxSettings:
    """Typed configuration for the sandbox execution service.

    Resource limits are defence-in-depth: the real isolation boundary is the
    container itself (non-root, dropped caps, private network, cgroup cpu/mem/
    pids caps set in compose). These per-command rlimits guard against a single
    runaway command; each is skipped when set to 0 so builds that legitimately
    need lots of memory or CPU are not killed by an overly tight limit.
    """

    port: int
    auth_token: str | None
    workspace_root: str
    command_timeout_seconds: float
    cpu_seconds: int
    memory_bytes: int
    fsize_bytes: int
    nofile_limit: int
    max_output_chars: int
    idle_timeout_seconds: float

    @classmethod
    def from_env(cls) -> "SandboxSettings":
        return cls(
            port=int(os.getenv("PORT", "7860")),
            auth_token=_optional_env("SANDBOX_AUTH_TOKEN"),
            workspace_root=os.getenv("SANDBOX_WORKSPACE_ROOT", "/workspace"),
            command_timeout_seconds=float(
                os.getenv("SANDBOX_COMMAND_TIMEOUT_SECONDS", "120")
            ),
            cpu_seconds=int(os.getenv("SANDBOX_CPU_SECONDS", "0")),
            # RLIMIT_AS breaks node/interpreters that over-reserve virtual memory;
            # default 0 (off) and rely on the container's cgroup memory cap.
            memory_bytes=int(os.getenv("SANDBOX_MEMORY_BYTES", "0")),
            fsize_bytes=int(
                os.getenv("SANDBOX_FSIZE_BYTES", str(500 * 1024 * 1024))
            ),
            nofile_limit=int(os.getenv("SANDBOX_NOFILE_LIMIT", "4096")),
            max_output_chars=int(os.getenv("SANDBOX_MAX_OUTPUT_CHARS", "20000")),
            idle_timeout_seconds=float(
                os.getenv("SANDBOX_IDLE_TIMEOUT_SECONDS", "3600")
            ),
        )


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    return value


SETTINGS = SandboxSettings.from_env()
