import ast
import unittest
from types import SimpleNamespace
from typing import Any, cast

from app.agent.capabilities.sandbox import (
    SandboxTools,
    _generate_chart_code,
    _resolve_filename,
)


def fake_ctx(*, file_ids=None, document_store=None) -> Any:
    return cast(
        Any,
        SimpleNamespace(
            deps=SimpleNamespace(file_ids=file_ids or [], document_store=document_store)
        ),
    )


class FakeStore:
    def __init__(self, files: dict[str, dict]):
        self.files = files

    async def get_file(self, file_id: str):
        return self.files.get(file_id)


class AllowedFileIdsTest(unittest.TestCase):
    def test_none_returns_empty_list(self):
        tools = SandboxTools()
        self.assertEqual(tools._allowed_file_ids(fake_ctx(), None), [])

    def test_empty_list_returns_empty_list(self):
        tools = SandboxTools()
        self.assertEqual(tools._allowed_file_ids(fake_ctx(file_ids=["file_1"]), []), [])

    def test_attached_file_id_passes_through(self):
        tools = SandboxTools()
        ctx = fake_ctx(file_ids=["file_1", "file_2"])
        self.assertEqual(tools._allowed_file_ids(ctx, ["file_1"]), ["file_1"])

    def test_unattached_file_id_raises(self):
        tools = SandboxTools()
        ctx = fake_ctx(file_ids=["file_1"])
        with self.assertRaisesRegex(ValueError, "not attached"):
            tools._allowed_file_ids(ctx, ["file_unknown"])

    def test_truncates_to_max_input_files(self):
        tools = SandboxTools(max_input_files=2)
        ctx = fake_ctx(file_ids=["file_1", "file_2", "file_3"])
        selected = tools._allowed_file_ids(ctx, ["file_1", "file_2", "file_3"])
        self.assertEqual(selected, ["file_1", "file_2"])


class ResolveFilenameTest(unittest.IsolatedAsyncioTestCase):
    async def test_no_document_store_raises(self):
        with self.assertRaisesRegex(ValueError, "not configured"):
            await _resolve_filename(fake_ctx(), "file_1")

    async def test_missing_file_raises(self):
        ctx = fake_ctx(document_store=FakeStore({}))
        with self.assertRaisesRegex(ValueError, "not found"):
            await _resolve_filename(ctx, "file_missing")

    async def test_known_file_returns_filename(self):
        store = FakeStore({"file_1": {"filename": "data.csv"}})
        ctx = fake_ctx(document_store=store)
        self.assertEqual(await _resolve_filename(ctx, "file_1"), "data.csv")


class GenerateChartCodeTest(unittest.TestCase):
    def test_unsupported_kind_raises(self):
        with self.assertRaisesRegex(ValueError, "Unsupported chart kind"):
            _generate_chart_code("data.csv", {"kind": "pie", "x": "a", "y": "b"})

    def test_missing_x_raises(self):
        with self.assertRaisesRegex(ValueError, "chart_spec.x"):
            _generate_chart_code("data.csv", {"kind": "line", "y": "b"})

    def test_missing_y_raises_for_line(self):
        with self.assertRaisesRegex(ValueError, "chart_spec.y"):
            _generate_chart_code("data.csv", {"kind": "line", "x": "a"})

    def test_hist_does_not_require_y(self):
        code = _generate_chart_code("data.csv", {"kind": "hist", "x": "a"})
        ast.parse(code)
        self.assertIn("kind='hist'", code)

    def test_valid_spec_produces_parseable_source(self):
        code = _generate_chart_code(
            "data.csv", {"kind": "bar", "x": "category", "y": "value", "title": "Totals"}
        )
        tree = ast.parse(code)
        self.assertTrue(any(isinstance(node, ast.Assign) for node in tree.body))
        self.assertIn("df.plot(kind='bar'", code)

    def test_adversarial_title_does_not_break_out_of_string_literal(self):
        adversarial = "'); import os; os.system('id'); #"
        code = _generate_chart_code(
            "data.csv", {"kind": "line", "x": "a", "y": "b", "title": adversarial}
        )
        # Must still parse as a single valid module - if repr() failed to
        # neutralize the value, this would either fail to parse or produce
        # extra executable statements.
        tree = ast.parse(code)
        call_count = sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "system"
        )
        self.assertEqual(call_count, 0)

    def test_adversarial_filename_does_not_break_out_of_string_literal(self):
        adversarial = "x.csv'); import os; os.system('id'); #"
        code = _generate_chart_code(adversarial, {"kind": "line", "x": "a", "y": "b"})
        tree = ast.parse(code)
        call_count = sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "system"
        )
        self.assertEqual(call_count, 0)


if __name__ == "__main__":
    unittest.main()
