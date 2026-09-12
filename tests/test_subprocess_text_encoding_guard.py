from __future__ import annotations

import ast
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCANNED_ROOTS = ("scripts", "hooks", "tools", "tests")
TEXT_SUBPROCESS_CALLS = {
    "Popen",
    "call",
    "check_call",
    "check_output",
    "getoutput",
    "getstatusoutput",
    "run",
}
ALWAYS_TEXT_SUBPROCESS_CALLS = {"getoutput", "getstatusoutput"}


def _keyword_node(call: ast.Call, name: str) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _is_required_value_or_none(node: ast.expr | None, required: str) -> bool:
    if isinstance(node, ast.Constant):
        return node.value == required
    return (
        isinstance(node, ast.IfExp)
        and isinstance(node.body, ast.Constant)
        and node.body.value == required
        and isinstance(node.orelse, ast.Constant)
        and node.orelse.value is None
    )


def _subprocess_call_names(tree: ast.AST) -> tuple[set[str], set[str]]:
    modules = {"subprocess"}
    functions: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "subprocess":
                    modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            for alias in node.names:
                if alias.name in TEXT_SUBPROCESS_CALLS:
                    functions.add(alias.asname or alias.name)
    return modules, functions


def _is_subprocess_call(
    call: ast.Call, modules: set[str], functions: set[str]
) -> bool:
    if isinstance(call.func, ast.Name):
        return call.func.id in functions
    return (
        isinstance(call.func, ast.Attribute)
        and call.func.attr in TEXT_SUBPROCESS_CALLS
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id in modules
    )


def _is_text_mode(call: ast.Call) -> bool:
    if isinstance(call.func, ast.Name):
        function_name = call.func.id
    elif isinstance(call.func, ast.Attribute):
        function_name = call.func.attr
    else:
        function_name = ""
    return function_name in ALWAYS_TEXT_SUBPROCESS_CALLS or any(
        keyword.arg in {"text", "universal_newlines", "encoding", "errors"}
        and not (
            isinstance(keyword.value, ast.Constant)
            and keyword.value.value in {False, None}
        )
        for keyword in call.keywords
    )


def find_unsafe_text_subprocess_calls() -> list[str]:
    violations: list[str] = []
    for root_name in SCANNED_ROOTS:
        for path in sorted((REPO_ROOT / root_name).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            modules, functions = _subprocess_call_names(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if not _is_subprocess_call(node, modules, functions):
                    continue
                if not _is_text_mode(node):
                    continue
                encoding = _keyword_node(node, "encoding")
                errors = _keyword_node(node, "errors")
                if not _is_required_value_or_none(
                    encoding, "utf-8"
                ) or not _is_required_value_or_none(errors, "replace"):
                    relative = path.relative_to(REPO_ROOT).as_posix()
                    violations.append(
                        f"{relative}:{node.lineno}: text subprocess requires "
                        'encoding="utf-8", errors="replace"'
                    )
    return violations


class SubprocessTextEncodingGuardTests(unittest.TestCase):
    def test_all_text_subprocess_calls_fix_encoding_and_errors(self) -> None:
        violations = find_unsafe_text_subprocess_calls()
        self.assertFalse(violations, "\n" + "\n".join(violations))

    def test_invalid_utf8_is_visible_instead_of_silent_none(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'\\xff')"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )

        self.assertEqual(completed.stdout, "\N{REPLACEMENT CHARACTER}")
        self.assertEqual(completed.stderr, "")


if __name__ == "__main__":
    unittest.main()
