import asyncio
import tempfile
import unittest
from pathlib import Path

from app.config import SandboxSettings
from app.workspace import (
    InvalidConversationError,
    NotFoundError,
    PathEscapeError,
    WorkspaceManager,
)


def _settings(root: str, **overrides) -> SandboxSettings:
    base = {
        "port": 7860,
        "auth_token": None,
        "workspace_root": root,
        "command_timeout_seconds": 10,
        "cpu_seconds": 0,
        "memory_bytes": 0,
        "fsize_bytes": 50 * 1024 * 1024,
        "nofile_limit": 1024,
        "max_output_chars": 20000,
        "idle_timeout_seconds": 3600,
    }
    base.update(overrides)
    return SandboxSettings(**base)


class WorkspacePathTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ws-path-")
        self.manager = WorkspaceManager(_settings(self.tmp))

    def test_resolve_stays_inside_workspace(self):
        resolved = self.manager.resolve("conv1", "sub/report.txt")
        base = Path(self.tmp).resolve() / "conv1"
        self.assertTrue(resolved.is_relative_to(base))

    def test_resolve_rejects_parent_traversal(self):
        with self.assertRaises(PathEscapeError):
            self.manager.resolve("conv1", "../../etc/passwd")

    def test_resolve_treats_absolute_as_workspace_relative(self):
        resolved = self.manager.resolve("conv1", "/etc/passwd")
        base = Path(self.tmp).resolve() / "conv1"
        self.assertEqual(resolved, base / "etc/passwd")

    def test_invalid_conversation_id_rejected(self):
        with self.assertRaises(InvalidConversationError):
            self.manager.resolve("../evil", "x.txt")

    def test_dot_conversation_ids_rejected_everywhere(self):
        # "." and ".." bypass resolve() via _conversation_dir/destroy, so they
        # must be rejected at the id level (they would otherwise hit the root).
        for bad in (".", ".."):
            with self.assertRaises(InvalidConversationError):
                self.manager.ensure(bad)
            with self.assertRaises(InvalidConversationError):
                self.manager.destroy(bad)
            with self.assertRaises(InvalidConversationError):
                asyncio.run(self.manager.exec(bad, "echo hi"))


class WorkspaceFsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ws-fs-")
        self.manager = WorkspaceManager(_settings(self.tmp))

    def test_write_and_read_roundtrip(self):
        self.manager.write_file("c", "notes/a.txt", b"hello world")
        self.assertEqual(self.manager.read_file("c", "notes/a.txt"), b"hello world")

    def test_read_missing_raises_not_found(self):
        with self.assertRaises(NotFoundError):
            self.manager.read_file("c", "nope.txt")

    def test_list_dir_reports_entries(self):
        self.manager.write_file("c", "a.txt", b"x")
        self.manager.make_dir("c", "sub")
        names = {node.name for node in self.manager.list_dir("c", ".")}
        self.assertEqual(names, {"a.txt", "sub"})

    def test_move_and_delete(self):
        self.manager.write_file("c", "a.txt", b"x")
        self.manager.move("c", "a.txt", "b.txt")
        self.assertEqual(self.manager.read_file("c", "b.txt"), b"x")
        self.manager.delete("c", "b.txt")
        with self.assertRaises(NotFoundError):
            self.manager.read_file("c", "b.txt")

    def test_destroy_removes_workspace(self):
        self.manager.write_file("c", "a.txt", b"x")
        self.manager.destroy("c")
        self.assertFalse((Path(self.tmp) / "c").exists())


class WorkspaceExecTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ws-exec-")

    def _run(self, command, **overrides):
        manager = WorkspaceManager(_settings(self.tmp, **overrides))
        return asyncio.run(manager.exec("c", command))

    def test_exec_captures_stdout_and_ok_status(self):
        result = self._run("echo hello-workspace")
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.exit_code, 0)
        self.assertIn("hello-workspace", result.stdout)

    def test_exec_nonzero_exit_is_error(self):
        result = self._run("echo oops >&2; exit 3")
        self.assertEqual(result.status, "error")
        self.assertEqual(result.exit_code, 3)
        self.assertIn("oops", result.stderr)

    def test_exec_runs_in_conversation_workspace(self):
        self._run("echo persisted > out.txt")
        manager = WorkspaceManager(_settings(self.tmp))
        self.assertEqual(manager.read_file("c", "out.txt").strip(), b"persisted")

    def test_exec_times_out_and_is_killed(self):
        manager = WorkspaceManager(_settings(self.tmp))
        result = asyncio.run(manager.exec("c", "sleep 5", timeout_seconds=1))
        self.assertEqual(result.status, "timeout")
        self.assertTrue(result.timed_out)
        self.assertLess(result.duration_ms, 4000)

    def test_exec_truncates_output(self):
        result = self._run("printf 'x%.0s' $(seq 1 500)", max_output_chars=100)
        self.assertLessEqual(len(result.stdout), 100)

    def test_exec_timeout_covers_process_that_closes_pipes(self):
        # Closes stdout+stderr (drain loop ends normally) but keeps running —
        # the timeout must still fire on the final wait, not hang.
        manager = WorkspaceManager(_settings(self.tmp))
        result = asyncio.run(
            manager.exec("c", "exec 1>&- 2>&-; sleep 5", timeout_seconds=1)
        )
        self.assertEqual(result.status, "timeout")
        self.assertLess(result.duration_ms, 4000)

    def test_exec_stream_yields_chunks_then_result(self):
        manager = WorkspaceManager(_settings(self.tmp))

        async def collect():
            events = []
            async for event in manager.exec_stream("c", "echo streamed"):
                events.append(event)
            return events

        events = asyncio.run(collect())
        self.assertEqual(events[-1]["type"], "result")
        self.assertEqual(events[-1]["status"], "ok")
        stdout_chunks = [e["text"] for e in events if e["type"] == "stdout"]
        self.assertTrue(any("streamed" in chunk for chunk in stdout_chunks))


if __name__ == "__main__":
    unittest.main()
