from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FACADE = ROOT / "scripts" / "kb" / "intent_guardian.py"
PARTS = ROOT / "scripts" / "kb" / "intent_guardian_parts"


class IntentGuardianSplitArchitectureTests(unittest.TestCase):
    def test_facade_and_component_line_limits(self) -> None:
        self.assertLessEqual(len(FACADE.read_text(encoding="utf-8").splitlines()), 6500)
        for path in sorted(PARTS.glob("*.py")):
            with self.subTest(module=path.name):
                self.assertLessEqual(
                    len(path.read_text(encoding="utf-8").splitlines()),
                    3000,
                )

    def test_component_import_graph_is_acyclic_and_never_imports_facade(self) -> None:
        graph: dict[str, set[str]] = {}
        for path in sorted(PARTS.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            dependencies: set[str] = set()
            for node in tree.body:
                if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
                    dependencies.add(node.module)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    self.assertFalse(
                        any(
                            isinstance(child, (ast.Import, ast.ImportFrom))
                            for child in ast.walk(node)
                        ),
                        f"delayed import in {path.name}:{node.name}",
                    )
            self.assertNotIn("intent_guardian", dependencies)
            graph[path.stem] = dependencies

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(module: str) -> None:
            if module in visiting:
                self.fail(f"component import cycle reaches {module}")
            if module in visited:
                return
            visiting.add(module)
            for dependency in graph.get(module, set()):
                visit(dependency)
            visiting.remove(module)
            visited.add(module)

        for module in graph:
            visit(module)

    def test_facade_contains_imports_not_duplicate_implementations(self) -> None:
        tree = ast.parse(FACADE.read_text(encoding="utf-8"))
        implementations = [
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]
        self.assertEqual(implementations, [])


if __name__ == "__main__":
    unittest.main()
