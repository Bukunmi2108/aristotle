import ast


FORBIDDEN_CALLS = {"exec", "eval", "compile", "__import__", "globals", "locals", "vars"}


def validate_python_source(code: str, allowed_imports: set[str]) -> None:
    """Cheap pre-filter: reject obviously unsafe code before spawning a process.

    Not the security boundary (that's the sandboxed subprocess's seccomp
    filter) — this only catches obvious problems early and cheaply.
    """
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        raise ValueError(f"Code failed to parse: {exc}") from exc

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _check_import(alias.name, allowed_imports)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                _check_import(node.module, allowed_imports)
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                raise ValueError(f"Access to '{node.attr}' is not allowed.")
        elif isinstance(node, ast.Name):
            if node.id.startswith("__") and node.id.endswith("__"):
                raise ValueError(f"Access to '{node.id}' is not allowed.")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in FORBIDDEN_CALLS:
                raise ValueError(f"Call to '{func.id}' is not allowed.")


def _check_import(module_name: str, allowed_imports: set[str]) -> None:
    top_level = module_name.split(".")[0]
    if top_level not in allowed_imports:
        raise ValueError(f"Import of '{module_name}' is not allowed.")
