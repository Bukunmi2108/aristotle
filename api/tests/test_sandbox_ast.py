import unittest

from app.services.sandbox_ast import validate_python_source


ALLOWED = {"math", "json", "pandas"}


class ValidatePythonSourceTest(unittest.TestCase):
    def test_allowed_import_passes(self):
        validate_python_source("import math\nprint(math.sqrt(4))", ALLOWED)

    def test_allowed_submodule_import_passes(self):
        validate_python_source("import pandas.testing", ALLOWED)

    def test_disallowed_import_raises(self):
        with self.assertRaisesRegex(ValueError, "not allowed"):
            validate_python_source("import os", ALLOWED)

    def test_disallowed_from_import_raises(self):
        with self.assertRaisesRegex(ValueError, "not allowed"):
            validate_python_source("from os import system", ALLOWED)

    def test_dunder_attribute_access_raises(self):
        with self.assertRaisesRegex(ValueError, "not allowed"):
            validate_python_source("(1).__class__", ALLOWED)

    def test_dunder_name_raises(self):
        with self.assertRaisesRegex(ValueError, "not allowed"):
            validate_python_source("print(__builtins__)", ALLOWED)

    def test_eval_call_raises(self):
        with self.assertRaisesRegex(ValueError, "not allowed"):
            validate_python_source("eval('1+1')", ALLOWED)

    def test_exec_call_raises(self):
        with self.assertRaisesRegex(ValueError, "not allowed"):
            validate_python_source("exec('print(1)')", ALLOWED)

    def test_syntax_error_raises_value_error(self):
        with self.assertRaisesRegex(ValueError, "failed to parse"):
            validate_python_source("def (", ALLOWED)

    def test_plain_arithmetic_passes(self):
        validate_python_source("result = 1 + 2 * 3", ALLOWED)


if __name__ == "__main__":
    unittest.main()
