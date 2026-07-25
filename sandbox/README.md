# Aristotle Sandbox

Private code-execution and workspace service for Aristotle.

The sandbox is the **only** component that runs untrusted, agent-written code and
the **only** owner of workspace files. It is never exposed publicly: the API
reaches it by container name over a private internal Docker network, guarded by a
bearer token. It holds no application secrets and no database credentials.

## Isolation model

The security boundary is the container, not any in-process check:

- runs as a non-root user;
- deployed with `cap_drop: ALL`, `no-new-privileges`, a read-only rootfs (except
  `/workspace` and `/tmp`), and cgroup cpu/memory/pids caps (compose);
- joined only to the private `aristotle_internal` network — no Postgres, no other
  project, no public edge;
- per-command wall-clock timeout + optional `rlimit`s (defence-in-depth);
- every filesystem path is validated against the per-conversation workspace root.

Between-conversation isolation is *soft* (each conversation is a subdirectory),
which is acceptable for a personal single-user tool. Future hardening: seccomp
syscall filtering and/or a `runsc` (gVisor) runtime.

## API

All `/workspaces/*` routes require `Authorization: Bearer <SANDBOX_AUTH_TOKEN>`.

```text
GET    /healthz                              process liveness
GET    /readyz                               workspace root writable
POST   /workspaces/{cid}/exec                run a command, return result
GET    /workspaces/{cid}/list?path=          list a directory
GET    /workspaces/{cid}/file?path=          read a file (bytes)
PUT    /workspaces/{cid}/file?path=          write a file (raw body)
POST   /workspaces/{cid}/mkdir               create a directory
POST   /workspaces/{cid}/move                move/rename a path
DELETE /workspaces/{cid}/file?path=          delete a path
DELETE /workspaces/{cid}                     destroy a workspace
```

## Local run

```sh
cd sandbox
uv sync
SANDBOX_WORKSPACE_ROOT=/tmp/aristotle-workspace \
uv run uvicorn app.main:app --reload --port 8500
```

## Tests

```sh
cd sandbox
uv run python -m unittest discover -s tests
```
