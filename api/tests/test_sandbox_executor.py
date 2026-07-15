import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from app.services.sandbox import SandboxExecutor


def make_settings(**overrides: Any) -> Any:
    defaults = dict(
        sandbox_allowed_imports="math,statistics,json,re,datetime,itertools,collections,csv",
        sandbox_cpu_seconds=2,
        sandbox_memory_bytes=200 * 1024 * 1024,
        sandbox_fsize_bytes=10 * 1024 * 1024,
        sandbox_nofile_limit=64,
        sandbox_run_timeout_seconds=5,
        sandbox_max_output_chars=200,
        sandbox_workspace_dir="",
        sandbox_artifact_dir="",
    )
    defaults.update(overrides)
    return cast(Any, SimpleNamespace(**defaults))


class FakeFileStore:
    """Minimal document-store double: file lookups plus optional recording
    of sandbox-run/artifact persistence calls, matching PersistenceStore's
    duck-typed interface."""

    def __init__(self, files: dict[str, dict] | None = None):
        self.files = files or {}
        self.sandbox_runs: list[dict] = []
        self.completed_runs: list[dict] = []
        self.artifacts: list[dict] = []

    async def get_file(self, file_id: str):
        return self.files.get(file_id)

    async def create_sandbox_run(self, **kwargs):
        self.sandbox_runs.append(kwargs)

    async def complete_sandbox_run(self, sandbox_run_id, **kwargs):
        self.completed_runs.append({"sandbox_run_id": sandbox_run_id, **kwargs})

    async def create_artifact(self, **kwargs):
        self.artifacts.append(kwargs)


class SandboxExecutorTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.workspace_root = tempfile.mkdtemp(prefix="aristotle-sandbox-test-")
        self.artifact_root = tempfile.mkdtemp(prefix="aristotle-artifact-test-")

    def tearDown(self):
        shutil.rmtree(self.workspace_root, ignore_errors=True)
        shutil.rmtree(self.artifact_root, ignore_errors=True)

    def _executor(self, *, document_store=None, **settings_overrides: Any) -> SandboxExecutor:
        settings = make_settings(
            sandbox_workspace_dir=self.workspace_root,
            sandbox_artifact_dir=self.artifact_root,
            **settings_overrides,
        )
        return SandboxExecutor(settings=settings, document_store=document_store)

    async def test_network_call_is_cleanly_blocked(self):
        executor = self._executor()
        session = executor.get_session("run_1", "conv_1")
        code = (
            "import socket\n"
            "try:\n"
            "    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
            "    s.connect(('1.1.1.1', 80))\n"
            "    print('CONNECTED')\n"
            "except OSError as e:\n"
            "    print('BLOCKED')\n"
        )
        # socket is stdlib and not in the AST allow-list by default, so allow it
        # for this test to reach the actual seccomp boundary rather than the
        # cheap pre-filter.
        session.settings = make_settings(
            sandbox_workspace_dir=self.workspace_root,
            sandbox_artifact_dir=self.artifact_root,
            sandbox_allowed_imports="socket",
        )
        result = await session.run(code)
        self.assertIn("BLOCKED", result.stdout)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.status, "ok")
        await executor.close_session("run_1")

    async def test_infinite_loop_is_killed_within_deadline(self):
        executor = self._executor(sandbox_cpu_seconds=1, sandbox_run_timeout_seconds=5)
        session = executor.get_session("run_2", "conv_1")
        result = await session.run("while True:\n    pass\n")
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn(result.status, {"error", "timeout"})
        await executor.close_session("run_2")

    async def test_disallowed_import_never_spawns_process(self):
        executor = self._executor()
        session = executor.get_session("run_3", "conv_1")
        result = await session.run("import os\nos.system('echo hi')")
        self.assertEqual(result.exit_code, -1)
        self.assertEqual(result.status, "rejected")
        self.assertIn("not allowed", result.stderr)
        self.assertEqual(result.duration_ms, 0)
        await executor.close_session("run_3")

    async def test_output_is_truncated_to_configured_limit(self):
        executor = self._executor(sandbox_max_output_chars=50)
        session = executor.get_session("run_4", "conv_1")
        result = await session.run("print('x' * 1000)")
        self.assertLessEqual(len(result.stdout), 50)
        await executor.close_session("run_4")

    async def test_written_file_is_collected_as_artifact(self):
        executor = self._executor()
        session = executor.get_session("run_5", "conv_1")
        code = "open('output.txt', 'w').write('hello')\n"
        result = await session.run(code)
        self.assertEqual(len(result.artifacts), 1)
        self.assertEqual(result.artifacts[0].filename, "output.txt")
        self.assertEqual(result.artifacts[0].size_bytes, 5)
        await executor.close_session("run_5")

    async def test_session_persists_files_across_calls(self):
        executor = self._executor()
        session = executor.get_session("run_6", "conv_1")
        await session.run("open('shared.txt', 'w').write('persisted')\n")
        result = await session.run(
            "print(open('shared.txt').read())\n"
        )
        self.assertIn("persisted", result.stdout)
        await executor.close_session("run_6")

    async def test_close_session_removes_workspace(self):
        executor = self._executor()
        session = executor.get_session("run_7", "conv_1")
        workspace_dir = session.workspace_dir
        self.assertTrue(workspace_dir.exists())
        await executor.close_session("run_7")
        self.assertFalse(workspace_dir.exists())

    async def test_artifact_file_survives_session_close(self):
        # Regression test: artifacts must be downloadable AFTER the chat turn
        # ends, not just while the session's workspace still exists.
        executor = self._executor()
        session = executor.get_session("run_8", "conv_1")
        result = await session.run("open('output.txt', 'w').write('hello')\n")
        artifact_id = result.artifacts[0].id

        await executor.close_session("run_8")

        artifact_path = Path(self.artifact_root) / artifact_id / "output.txt"
        self.assertTrue(artifact_path.exists(), "artifact file was deleted with the workspace")
        self.assertEqual(artifact_path.read_text(), "hello")

    async def test_get_session_returns_same_object_for_same_run_id(self):
        executor = self._executor()
        first = executor.get_session("run_9", "conv_1")
        second = executor.get_session("run_9", "conv_1")
        self.assertIs(first, second)
        await executor.close_session("run_9")

    async def test_different_run_ids_get_isolated_workspaces(self):
        executor = self._executor()
        session_a = executor.get_session("run_a", "conv_1")
        session_b = executor.get_session("run_b", "conv_1")
        self.assertNotEqual(session_a.workspace_dir, session_b.workspace_dir)

        await session_a.run("open('only_in_a.txt', 'w').write('a')\n")
        result = await session_b.run(
            "import os\nprint(os.path.exists('only_in_a.txt'))\n"
        )
        self.assertIn("False", result.stdout)
        await executor.close_session("run_a")
        await executor.close_session("run_b")

    async def test_evict_stale_sessions_replaces_old_workspace(self):
        executor = self._executor(sandbox_run_timeout_seconds=0.01)
        session = executor.get_session("run_10", "conv_1")
        old_workspace = session.workspace_dir
        session.created_at -= 100  # force staleness without a real sleep

        new_session = executor.get_session("run_10", "conv_1")
        self.assertIsNot(session, new_session)
        self.assertFalse(old_workspace.exists())
        await executor.close_session("run_10")

    async def test_materialize_files_copies_from_store_and_reuses_cache(self):
        source_path = Path(tempfile.mkdtemp(prefix="aristotle-source-"))
        try:
            source_file = source_path / "original"
            source_file.write_text("v1")
            store = FakeFileStore({"file_1": {"storage_path": str(source_file), "filename": "data.csv"}})
            executor = self._executor(document_store=store)
            session = executor.get_session("run_11", "conv_1")

            result = await session.run("print(open('data.csv').read())\n", ["file_1"])
            self.assertIn("v1", result.stdout)

            # Mutate the source after first materialization; a second run
            # with the same file_id must not re-copy (proves the
            # `_materialized_file_ids` cache path is exercised).
            source_file.write_text("v2")
            result2 = await session.run("print(open('data.csv').read())\n", ["file_1"])
            self.assertIn("v1", result2.stdout)
            self.assertNotIn("v2", result2.stdout)
            await executor.close_session("run_11")
        finally:
            shutil.rmtree(source_path, ignore_errors=True)

    async def test_materialize_files_sanitizes_path_traversal_filename(self):
        source_path = Path(tempfile.mkdtemp(prefix="aristotle-source-"))
        try:
            source_file = source_path / "original"
            source_file.write_text("payload")
            escape_target = Path(self.workspace_root) / "escaped.txt"
            store = FakeFileStore(
                {"file_1": {"storage_path": str(source_file), "filename": "../escaped.txt"}}
            )
            executor = self._executor(document_store=store)
            session = executor.get_session("run_12", "conv_1")

            await session.run("pass\n", ["file_1"])

            self.assertFalse(escape_target.exists(), "path traversal escaped the workspace dir")
            self.assertTrue((session.workspace_dir / "escaped.txt").exists())
            await executor.close_session("run_12")
        finally:
            shutil.rmtree(source_path, ignore_errors=True)

    async def test_materialize_files_missing_file_adds_stderr_warning(self):
        store = FakeFileStore({})
        executor = self._executor(document_store=store)
        session = executor.get_session("run_13", "conv_1")
        result = await session.run("pass\n", ["file_missing"])
        self.assertIn("could not be loaded", result.stderr)
        await executor.close_session("run_13")

    async def test_db_persistence_call_contract(self):
        store = FakeFileStore()
        executor = self._executor(document_store=store)
        session = executor.get_session("run_14", "conv_1")

        await session.run("print('ok')\n")
        self.assertEqual(len(store.sandbox_runs), 1)
        self.assertEqual(store.sandbox_runs[0]["run_id"], "run_14")
        self.assertEqual(store.sandbox_runs[0]["conversation_id"], "conv_1")
        self.assertEqual(len(store.completed_runs), 1)
        self.assertEqual(store.completed_runs[0]["status"], "complete")

        await session.run("import sys\nsys.exit(1)\n")
        self.assertEqual(store.completed_runs[1]["status"], "error")

        await executor.close_session("run_14")

    async def test_db_error_does_not_lose_successful_result(self):
        store = FakeFileStore()

        async def broken_complete(*args, **kwargs):
            raise RuntimeError("db is down")

        store.complete_sandbox_run = broken_complete  # type: ignore[method-assign]
        executor = self._executor(document_store=store)
        session = executor.get_session("run_15", "conv_1")

        result = await session.run("print('still works')\n")
        self.assertEqual(result.status, "ok")
        self.assertIn("still works", result.stdout)
        await executor.close_session("run_15")

    async def test_subprocess_spawn_failure_returns_clean_error_result(self):
        executor = self._executor()
        session = executor.get_session("run_16", "conv_1")

        with patch(
            "app.services.sandbox.asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError("python3 not found"),
        ):
            result = await session.run("print('hi')\n")

        self.assertEqual(result.status, "error")
        self.assertIn("failed to start", result.stderr)
        await executor.close_session("run_16")

    async def test_pandas_import_actually_works(self):
        # Regression test for the `-S` flag bug: `python3 -I -S` disabled
        # site-packages entirely, silently breaking every pandas/numpy/
        # matplotlib import. This must exercise the real interpreter flags,
        # not just the AST pre-filter.
        executor = self._executor(
            sandbox_allowed_imports="pandas,io",
        )
        session = executor.get_session("run_17", "conv_1")
        code = (
            "import pandas as pd\n"
            "df = pd.DataFrame({'a': [1, 2, 3]})\n"
            "print(int(df['a'].sum()))\n"
        )
        result = await session.run(code)
        self.assertEqual(result.stderr, "")
        self.assertIn("6", result.stdout)
        self.assertEqual(result.status, "ok")
        await executor.close_session("run_17")

    async def test_chart_generation_end_to_end(self):
        executor = self._executor(sandbox_allowed_imports="matplotlib")
        session = executor.get_session("run_18", "conv_1")
        code = (
            "import matplotlib\n"
            "matplotlib.use('Agg')\n"
            "import matplotlib.pyplot as plt\n"
            "fig, ax = plt.subplots()\n"
            "ax.plot([1, 2, 3], [1, 4, 9])\n"
            "fig.savefig('chart.png')\n"
        )
        result = await session.run(code)
        self.assertEqual(result.status, "ok", result.stderr)
        self.assertEqual(len(result.artifacts), 1)
        self.assertEqual(result.artifacts[0].mime_type, "image/png")
        await executor.close_session("run_18")

    async def test_sweep_orphaned_workspaces_on_construction(self):
        orphan_dir = Path(self.workspace_root) / "orphan_run"
        orphan_dir.mkdir(parents=True)
        old_time = os.stat(self.workspace_root).st_mtime - 100000
        os.utime(orphan_dir, (old_time, old_time))

        self._executor(sandbox_run_timeout_seconds=1)

        self.assertFalse(orphan_dir.exists())


if __name__ == "__main__":
    unittest.main()
