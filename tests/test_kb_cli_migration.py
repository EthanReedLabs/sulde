from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import venv
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_CALLERS = (
    "tools/kb-mcp/server.py",
    "scripts/kb/mem-golden.py",
    "tests/kb-golden-eval.py",
    "hooks/lib/mem_recall.py",
    "scripts/kb/auto-distill.py",
    "scripts/kb/auto-sediment.py",
    "hooks/lib/kb_recall.py",
    "hooks/lib/kb_freshness.py",
    "scripts/kb/mem-secret-scan.py",
    "scripts/kb/mem-sync.py",
)
PATH_NEUTRAL_CALLERS = RUNTIME_CALLERS[:-2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def create_fixture(root: Path, home: Path) -> Path:
    venv.EnvBuilder(with_pip=False).create(home / "venv")
    python = (
        home / "venv" / "Scripts" / "python.exe"
        if os.name == "nt"
        else home / "venv" / "bin" / "python"
    )
    entries = {
        root / "tools" / "kb-index" / "search.py": "print('[]')\n",
        root / "tools" / "kb-index" / "memory.py": (
            "import sys\n"
            "print('{}' if sys.argv[1] == 'annotate' else '[]')\n"
        ),
    }
    for path, source in entries.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    legacy = root / "scripts" / "kb" / "kb-index"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    return python


class MigratedCliLaunchTests(unittest.TestCase):
    def test_mcp_forced_cli_fallback_launches_the_venv_interpreter(self) -> None:
        server = load_module("test_migrated_kb_mcp", ROOT / "tools/kb-mcp/server.py")
        cases = (
            (server.kb_search, {"query": "query"}),
            (server.kb_related, {"doc_id": "ap-0001"}),
            (server.memory_search, {"query": "history"}),
            (server.memory_annotate, {"entities": [{"name": "A", "type": "component"}, {"name": "B", "type": "risk"}], "edges": [{"src": "A", "rel": "avoids", "dst": "B"}], "extracted_by": "codex"}),
            (server.memory_graph, {"entity": "entity"}),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "root"
            home = base / "home"
            expected_python = create_fixture(root, home)
            with mock.patch.dict(os.environ, {"SULDE_MCP_FORCE_CLI": "1"}), \
                 mock.patch.object(server, "repo_root", return_value=root), \
                 mock.patch.object(server, "kb_home", return_value=home):
                for caller, arguments in cases:
                    with self.subTest(caller=caller.__name__), \
                         mock.patch.object(
                             server.kb_cli.subprocess,
                             "run",
                             wraps=subprocess.run,
                         ) as run_spy:
                        response = caller(arguments)
                    self.assertNotIn("isError", response)
                    command = run_spy.call_args.args[0]
                    self.assertEqual(
                        run_spy.call_args.kwargs["env"]["SULDE_KB_HOME"],
                        str(home),
                    )
                    self.assertEqual(
                        Path(command[0]).resolve(), expected_python.resolve()
                    )

    def test_golden_callers_launch_the_venv_interpreter(self) -> None:
        memory_golden = load_module(
            "test_migrated_mem_golden", ROOT / "scripts/kb/mem-golden.py"
        )
        kb_golden = load_module(
            "test_migrated_kb_golden", ROOT / "tests/kb-golden-eval.py"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "root"
            home = base / "home"
            expected_python = create_fixture(root, home)
            data = base / "golden.jsonl"
            data.write_text(
                json.dumps(
                    {"query": "query", "expect": ["missing"], "note": "test"}
                )
                + "\n",
                encoding="utf-8",
            )
            environment = {"SULDE_KB_HOME": str(home)}
            with mock.patch.dict(os.environ, environment), \
                 mock.patch.object(memory_golden, "REPO_ROOT", root), \
                 mock.patch.object(
                     memory_golden.kb_cli.subprocess,
                     "run",
                     wraps=subprocess.run,
                 ) as memory_run:
                self.assertEqual(memory_golden.search("query", "project"), [])
            self.assertEqual(
                Path(memory_run.call_args.args[0][0]).resolve(),
                expected_python.resolve(),
            )
            self.assertIn("--skip-pending-embed", memory_run.call_args.args[0])

            arguments = [
                "kb-golden-eval.py",
                "--data",
                str(data),
                "--min-rate",
                "0",
            ]
            with mock.patch.dict(os.environ, environment), \
                 mock.patch.object(kb_golden, "ROOT", root), \
                 mock.patch.object(sys, "argv", arguments), \
                 mock.patch.object(
                     kb_golden.kb_cli.subprocess,
                     "run",
                     wraps=subprocess.run,
                 ) as kb_run:
                self.assertEqual(kb_golden.main(), 0)
            self.assertEqual(
                Path(kb_run.call_args.args[0][0]).resolve(),
                expected_python.resolve(),
            )

    def test_mcp_launch_failures_remain_tool_errors(self) -> None:
        server = load_module(
            "test_migrated_kb_mcp_failure", ROOT / "tools/kb-mcp/server.py"
        )
        failure = server.kb_cli.CliResult(
            "launch_failed", detail="OSError: synthetic launch failure"
        )
        cases = (
            (server.kb_search, {"query": "query"}),
            (server.kb_related, {"doc_id": "ap-0001"}),
            (server.memory_search, {"query": "history"}),
            (server.memory_annotate, {"entities": [{"name": "A", "type": "component"}, {"name": "B", "type": "risk"}], "edges": [{"src": "A", "rel": "avoids", "dst": "B"}], "extracted_by": "codex"}),
            (server.memory_graph, {"entity": "entity"}),
        )
        with mock.patch.dict(os.environ, {"SULDE_MCP_FORCE_CLI": "1"}), \
             mock.patch.object(server.kb_cli, "run_cli", return_value=failure):
            for caller, arguments in cases:
                with self.subTest(caller=caller.__name__):
                    response = caller(arguments)
                    self.assertIs(response.get("isError"), True)
                    self.assertIn(
                        "synthetic launch failure", response["content"][0]["text"]
                    )

    def test_golden_launch_failures_remain_visible(self) -> None:
        memory_golden = load_module(
            "test_migrated_mem_golden_failure", ROOT / "scripts/kb/mem-golden.py"
        )
        kb_golden = load_module(
            "test_migrated_kb_golden_failure", ROOT / "tests/kb-golden-eval.py"
        )
        failure = memory_golden.kb_cli.CliResult(
            "launch_failed", detail="OSError: synthetic golden failure"
        )
        with mock.patch.object(memory_golden.kb_cli, "run_cli", return_value=failure):
            with self.assertRaisesRegex(
                memory_golden.GoldenError, "synthetic golden failure"
            ):
                memory_golden.search("query", "project")

        with tempfile.TemporaryDirectory() as temp_dir:
            data = Path(temp_dir) / "golden.jsonl"
            data.write_text(
                json.dumps(
                    {"query": "query", "expect": ["missing"], "note": "test"}
                )
                + "\n",
                encoding="utf-8",
            )
            stderr = io.StringIO()
            with mock.patch.object(kb_golden.kb_cli, "run_cli", return_value=failure), \
                 mock.patch.object(
                     sys,
                     "argv",
                     ["kb-golden-eval.py", "--data", str(data), "--min-rate", "0"],
                 ), \
                 contextlib.redirect_stderr(stderr):
                self.assertEqual(kb_golden.main(), 2)
            self.assertIn("synthetic golden failure", stderr.getvalue())


class CliDriftGuardTests(unittest.TestCase):
    def test_repository_has_no_unexpected_public_cli_launcher_mapping(self) -> None:
        entry_allowlist = {
            "scripts/kb/launcher_contract.py",  # stable public launchers and their targets
            "scripts/kb/windows-task.py",  # deployment asset existence check
            "tests/p2_template_dryrun.py",  # staged-file manifest assertion
        }
        entry_fragments = (
            'scripts" / "kb" / "kb-index',
            "scripts/kb/kb-index",
            'tools" / "kb-index" / "build.py',
            'tools" / "kb-index" / "search.py',
            'tools" / "kb-index" / "memory.py',
            'root / f"{name}.py"',
        )
        unexpected: list[str] = []
        for directory in ("hooks", "scripts", "tools", "tests"):
            for path in (ROOT / directory).rglob("*.py"):
                relative = path.relative_to(ROOT).as_posix()
                if relative == "hooks/lib/kb_cli.py":
                    continue
                if directory == "tests" and path.name.startswith("test_"):
                    continue
                source = path.read_text(encoding="utf-8")
                if any(fragment in source for fragment in entry_fragments):
                    if relative not in entry_allowlist:
                        unexpected.append(f"entry:{relative}")
        self.assertEqual(unexpected, [])

    def test_repository_has_no_unexpected_venv_dual_candidate_resolution(self) -> None:
        interpreter_allowlist = {
            "hooks/lib/kb_cli.py",  # canonical runtime resolver
            "scripts/kb/configure-global.py",  # stage-three command rendering
            "scripts/kb/configure-statusline.py",  # stage-three config rendering
            "scripts/kb/launcher_contract.py",  # pins the installed cross-platform venv interpreter
        }
        unexpected: list[str] = []
        for directory in ("hooks", "scripts", "tools", "tests"):
            for path in (ROOT / directory).rglob("*.py"):
                relative = path.relative_to(ROOT).as_posix()
                if directory == "tests" and path.name.startswith("test_"):
                    continue
                source = path.read_text(encoding="utf-8")
                normalized = re.sub(
                    r"[^A-Za-z0-9_.]+", "/", source.replace("\\", "/")
                )
                normalized = re.sub(r"/+", "/", normalized)
                has_posix = "venv/bin/python" in normalized
                has_windows = "venv/Scripts/python.exe" in normalized
                if has_posix and has_windows and relative not in interpreter_allowlist:
                    unexpected.append(relative)
        self.assertEqual(unexpected, [])

    def test_runtime_callers_have_no_independent_launcher_mapping(self) -> None:
        forbidden_entry_fragments = (
            'scripts" / "kb" / "kb-index',
            'scripts/kb/kb-index',
            'tools" / "kb-index" / "memory.py',
            'root / f"{name}.py"',
        )
        for relative in RUNTIME_CALLERS:
            source = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(relative=relative):
                for fragment in forbidden_entry_fragments:
                    self.assertNotIn(fragment, source)
                self.assertFalse(
                    'venv" / "bin" / "python' in source
                    and 'venv" / "Scripts" / "python.exe' in source
                )

    def test_cross_directory_import_uses_one_path_neutral_mechanism(self) -> None:
        for relative in RUNTIME_CALLERS:
            source = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(relative=relative):
                self.assertIn("runpy.run_path", source)
                self.assertNotRegex(
                    source,
                    r"sys\.path\.insert\([\s\S]{0,200}(?:hooks|kb_cli)",
                )
                if relative in PATH_NEUTRAL_CALLERS and relative != "tools/kb-mcp/server.py":
                    self.assertNotIn("sys.path.insert", source)


if __name__ == "__main__":
    unittest.main()
