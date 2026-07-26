import asyncio
import unittest
from types import SimpleNamespace

from app.agent.capabilities.workspace import (
    WORKSPACE_TOOL_NAMES,
    CommandResult,
    WorkspaceTools,
    _command_result,
    _exists,
    _node_fields,
    _snapshot_path,
)
from app.services.sandbox_client import SandboxError


class FakeWorkspace:
    def __init__(self, entries=None, error=None):
        self._entries = entries or []
        self._error = error
        self.listed: list[str] = []

    async def list_dir(self, path):
        self.listed.append(path)
        if self._error is not None:
            raise self._error
        return self._entries


def _ctx(enabled: bool):
    return SimpleNamespace(deps=SimpleNamespace(workspace_tools_enabled=enabled))


class WorkspaceInstructionsTest(unittest.TestCase):
    def test_instructions_none_when_disabled(self):
        instructions = WorkspaceTools().get_instructions()
        self.assertIsNone(instructions(_ctx(False)))

    def test_instructions_present_when_enabled(self):
        instructions = WorkspaceTools().get_instructions()
        text = instructions(_ctx(True))
        self.assertIsNotNone(text)
        self.assertIn("workspace", text.lower())


class WorkspacePrepareToolsTest(unittest.TestCase):
    def _tool_defs(self):
        names = list(WORKSPACE_TOOL_NAMES) + ["search_web", "read_file_document"]
        return [SimpleNamespace(name=name) for name in names]

    def test_keeps_all_when_enabled(self):
        tools = WorkspaceTools()
        kept = asyncio.run(tools.prepare_tools(_ctx(True), self._tool_defs()))
        self.assertEqual(len(kept), len(self._tool_defs()))

    def test_filters_workspace_tools_when_disabled(self):
        tools = WorkspaceTools()
        kept = asyncio.run(tools.prepare_tools(_ctx(False), self._tool_defs()))
        kept_names = {tool.name for tool in kept}
        self.assertFalse(kept_names & WORKSPACE_TOOL_NAMES)
        self.assertIn("search_web", kept_names)


class WorkspaceToolsetTest(unittest.TestCase):
    def test_toolset_registers_exactly_the_expected_tools(self):
        toolset = WorkspaceTools().get_toolset()
        self.assertEqual(set(toolset.tools), WORKSPACE_TOOL_NAMES)

    def test_configured_capabilities_have_no_tool_name_conflicts(self):
        # Capabilities configured together in the spec share one tool namespace;
        # a duplicate name makes the whole agent fail to run (e.g. workspace vs
        # document read_file). Check exactly the set the spec loads.
        import yaml

        from app.agent.capabilities import CUSTOM_CAPABILITY_TYPES
        from app.agent.factory import AGENT_SPEC_PATH

        by_name = {cap.__name__: cap for cap in CUSTOM_CAPABILITY_TYPES}
        spec = yaml.safe_load(AGENT_SPEC_PATH.read_text())

        owner: dict[str, str] = {}
        for entry in spec.get("capabilities", []):
            cap_name = next(iter(entry)) if isinstance(entry, dict) else entry
            capability_type = by_name.get(cap_name)
            if capability_type is None:
                continue  # built-in capability (Thinking, ReinjectSystemPrompt)
            for name in capability_type().get_toolset().tools:
                self.assertNotIn(
                    name,
                    owner,
                    f"tool '{name}' defined by both {owner.get(name)} and {cap_name}",
                )
                owner[name] = cap_name


class WorkspaceHelpersTest(unittest.TestCase):
    def test_command_result_maps_all_fields(self):
        payload = {
            "status": "error",
            "stdout": "out",
            "stderr": "err",
            "exit_code": 2,
            "timed_out": False,
            "duration_ms": 12,
        }
        result = _command_result(payload)
        self.assertIsInstance(result, CommandResult)
        self.assertEqual(result.exit_code, 2)
        self.assertEqual(result.stderr, "err")

    def test_node_fields_projects_only_expected_keys(self):
        node = {"name": "a", "path": "a", "type": "file", "size": 3, "mtime": 9.0}
        self.assertEqual(
            _node_fields(node), {"name": "a", "path": "a", "type": "file", "size": 3}
        )

    def test_snapshot_path_is_immutable_and_preserves_safe_filename(self):
        self.assertEqual(
            _snapshot_path("pres_123", "reports/final report.html"),
            ".aristotle/presentations/pres_123/final report.html",
        )


class WorkspaceExistsTest(unittest.IsolatedAsyncioTestCase):
    async def test_true_when_file_present_in_subdir(self):
        workspace = FakeWorkspace([{"name": "summary.md"}, {"name": "notes.txt"}])
        self.assertTrue(await _exists(workspace, "report/summary.md"))
        self.assertEqual(workspace.listed, ["report"])

    async def test_root_level_file_lists_dot(self):
        workspace = FakeWorkspace([{"name": "index.html"}])
        self.assertTrue(await _exists(workspace, "index.html"))
        self.assertEqual(workspace.listed, ["."])

    async def test_false_when_absent(self):
        workspace = FakeWorkspace([{"name": "other.txt"}])
        self.assertFalse(await _exists(workspace, "report/summary.md"))

    async def test_false_on_sandbox_error(self):
        workspace = FakeWorkspace(error=SandboxError("unreachable"))
        self.assertFalse(await _exists(workspace, "x.txt"))


if __name__ == "__main__":
    unittest.main()
