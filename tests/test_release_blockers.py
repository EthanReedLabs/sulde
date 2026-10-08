"""Bounded release repair: preserve extracted behavior and import boundaries."""
from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PARTS = ROOT / "scripts/kb/intent_guardian_parts"
BASE = "b40c0a3b3edfc80dd357c895cff7cf26a4f148eb"
sys.path.insert(0, str(ROOT / "scripts/kb"))
import command_template
from intent_guardian_parts import historical_native_retirement as compatibility
from intent_guardian_parts import historical_retirement as historical
from intent_guardian_parts import native_binding, approvals, state, relocation_storage
from intent_guardian_parts import repository_relocation as relocation


class WithoutImports(ast.NodeTransformer):
    def visit_Import(self, node):
        return None

    def visit_ImportFrom(self, node):
        return None


class SnapshotBudgetNames(ast.NodeTransformer):
    def visit_Name(self, node):
        if node.id in {"max_bytes", "read_bytes"}:
            node.id = {"max_bytes": "MAX_STORE_BYTES", "read_bytes": "STORE_READ_BYTES"}[node.id]
        return node


def functions(source, *, explicit_snapshot_budgets=False):
    tree = WithoutImports().visit(ast.parse(source))
    if explicit_snapshot_budgets:
        snapshot = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_store_snapshot")
        assert [n.arg for n in snapshot.args.kwonlyargs[-2:]] == ["max_bytes", "read_bytes"]
        assert [ast.dump(n) for n in snapshot.args.kw_defaults[-2:]] == [
            ast.dump(ast.Name(id="MAX_STORE_BYTES", ctx=ast.Load())),
            ast.dump(ast.Name(id="STORE_READ_BYTES", ctx=ast.Load())),
        ]
        del snapshot.args.kwonlyargs[-2:]
        del snapshot.args.kw_defaults[-2:]
        SnapshotBudgetNames().visit(snapshot)
    return {n.name: ast.dump(n) for n in tree.body if isinstance(n, ast.FunctionDef)}


class ReleaseBlockerTests(unittest.TestCase):
    def test_extracted_primitives_keep_original_implementation(self):
        transfers = {
            ("state", "relocation_storage"): ("atomic_write", "_exclusive_path_lock"),
            ("repository_relocation", "relocation_storage"): (
                "_digest", "_canonical", "_git", "_read_plan_file", "_store_home",
                "_fence_directory", "_read_write_fences", "require_relocation_write_allowed",
                "relocation_registration_write", "_store_snapshot",
            ),
            ("approvals", "native_binding"): ("_native_card_sha256", "_native_binding_snapshot"),
            ("recovery", "native_decision_support"): ("_late_native_proposal_result",),
        }
        for (old, new), names in transfers.items():
            baseline = subprocess.check_output(
                ["git", "show", BASE + ":scripts/kb/intent_guardian_parts/" + old + ".py"],
                cwd=ROOT, text=True, encoding="utf-8", errors="replace",
            )
            before = functions(baseline)
            after = functions((PARTS / (new + ".py")).read_text(encoding="utf-8"),
                              explicit_snapshot_budgets=new == "relocation_storage")
            for name in names:
                with self.subTest(name=name):
                    self.assertEqual(before[name], after[name])

    def test_controller_capacity_and_chunk_size_remain_live_configuration_seams(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve() / "store"
            path.write_bytes(b"1234")
            with mock.patch.object(relocation, "MAX_STORE_BYTES", 4), \
                    mock.patch.object(relocation, "STORE_READ_BYTES", 2):
                with mock.patch.object(relocation_storage.os, "read",
                                       wraps=relocation_storage.os.read) as read:
                    self.assertEqual(relocation._store_snapshot(path)["size"], 4)
                    self.assertEqual({call.args[1] for call in read.call_args_list}, {2})
                path.write_bytes(b"12345")
                with self.assertRaisesRegex(state.IntentGuardianError, "per-file"):
                    relocation._store_snapshot(path)

    def test_compatibility_exports_share_one_implementation(self):
        self.assertIs(state.atomic_write, relocation_storage.atomic_write)
        self.assertIs(state._exclusive_path_lock, relocation_storage._exclusive_path_lock)
        self.assertIs(approvals._native_binding_snapshot, native_binding._native_binding_snapshot)
        for public, private in (("prepare", "_native_prepare"), ("execute", "_native_execute"),
                                ("context", "_native_context"), ("review_source", "_native_review_source")):
            self.assertIs(getattr(compatibility, public), getattr(historical, private))
        self.assertIs(compatibility.epoch, historical)
        self.assertIs(compatibility.journal, historical.journal)

    def test_ledger_first_import_orders_do_not_load_high_level_controllers(self):
        for first in ("approval_invariant", "intervention", "native_decision_journal",
                      "intent_guardian_parts.relocation_storage"):
            with self.subTest(first=first):
                code = (
                    "import sys, importlib; sys.path.insert(0, 'scripts/kb'); "
                    f"importlib.import_module({first!r}); "
                    "assert 'intent_guardian_parts.repository_relocation' not in sys.modules; "
                    "importlib.import_module('intent_guardian_parts.audit'); "
                    "importlib.import_module('intent_guardian_parts.recovery')"
                )
                result = subprocess.run(
                    [sys.executable, "-B", "-c", code], cwd=ROOT,
                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_git_review_uses_explicit_posix_parser_and_keeps_windows_closed(self):
        command = "cd '/tmp/repo with spaces' && git status --short | head -n 5"
        with mock.patch.object(command_template.os, "name", "posix"):
            with mock.patch.object(command_template, "split_command_template",
                                   wraps=command_template.split_command_template) as parser:
                self.assertTrue(command_template.git_stdin_review_pipeline(command))
                self.assertIn(mock.call("cd '/tmp/repo with spaces'", os_name="posix"), parser.call_args_list)
                self.assertIn(mock.call("head -n 5", os_name="posix"), parser.call_args_list)
            for unsafe in ("git status | head secrets.txt", "git status | head > out",
                           "git status | $(echo head)", "git status || head"):
                with self.subTest(unsafe=unsafe):
                    self.assertFalse(command_template.git_stdin_review_pipeline(unsafe))
        with mock.patch.object(command_template.os, "name", "nt"):
            with mock.patch.object(command_template, "split_command_template",
                                   side_effect=AssertionError("Windows must not use POSIX proof")):
                self.assertFalse(command_template.git_stdin_review_pipeline(command))
